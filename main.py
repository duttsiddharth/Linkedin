# ─────────────────────────────────────────────────────────────
#  main.py  |  LinkedIn AI Ghostwriter  |  FastAPI Backend
#  Stack: FastAPI · Gemini 1.5 Flash (free) · Supabase
# ─────────────────────────────────────────────────────────────
import os, uuid, asyncio, logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Clients ───────────────────────────────────────────────────
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini = genai.GenerativeModel("gemini-1.5-flash")  # free tier

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

app = FastAPI(
    title="LinkedIn AI Ghostwriter",
    description="AI-powered LinkedIn content pipeline",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic Models ───────────────────────────────────────────
class GenerateRequest(BaseModel):
    topic: str
    niche: str = "AI & Data Engineering"
    tone: str = "bold, insightful, slightly controversial"
    length: str = "150-250 words"
    user_id: str = "default"

class ApprovalRequest(BaseModel):
    post_id: str
    approved: bool

class ScheduleRequest(BaseModel):
    post_id: str
    schedule_at: datetime  # ISO 8601

# ── Prompt Builder ────────────────────────────────────────────
def build_prompt(r: GenerateRequest) -> str:
    return f"""
You are an elite LinkedIn ghostwriter and content strategist.
Write ONE viral LinkedIn post following these exact specs:

Topic: {r.topic}
Niche: {r.niche}
Tone: {r.tone}
Target length: {r.length}

MANDATORY STRUCTURE:
━━━━━━━━━━━━━━━━━━━
[HOOK]
Line 1 only. Scroll-stopping. Use ONE of:
  • A bold contrarian claim
  • A surprising data point
  • A short story opening
  • A direct challenge to the reader
NEVER start with "I am excited", "Thrilled to share", or similar.

[BODY — 3 to 5 paragraphs]
  • Short sentences. Max 2 lines per paragraph.
  • Add ONE concrete, relatable real-world example.
  • Add ONE personal insight or data point.
  • Use blank lines between paragraphs for breathing room.

[CTA — 1 line]
A genuine question that invites comments.
Not "What do you think?" — make it specific.

[HASHTAGS]
Exactly 5 hashtags on the final line.
━━━━━━━━━━━━━━━━━━━

Return ONLY the post text. No preamble, no explanation, no markdown wrapper.
""".strip()


# ── Duplicate topic guard ─────────────────────────────────────
def topic_is_duplicate(topic: str) -> bool:
    import hashlib
    h = hashlib.md5(topic.lower().strip().encode()).hexdigest()
    result = (
        supabase.table("used_topics")
        .select("id")
        .eq("topic_hash", h)
        .execute()
    )
    if result.data:
        return True
    supabase.table("used_topics").insert(
        {"topic_hash": h, "topic": topic}
    ).execute()
    return False


# ── Routes ────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/generate")
async def generate_post(req: GenerateRequest):
    """Generate a LinkedIn post via Gemini and store as 'pending'."""

    if topic_is_duplicate(req.topic):
        raise HTTPException(
            409,
            f"Topic '{req.topic}' was already used recently. Try a variation.",
        )

    prompt = build_prompt(req)
    try:
        resp = gemini.generate_content(prompt)
        content = resp.text.strip()
    except Exception as e:
        log.error("Gemini error: %s", e)
        raise HTTPException(500, f"AI generation failed: {e}")

    post_id = str(uuid.uuid4())
    supabase.table("posts").insert(
        {
            "id": post_id,
            "user_id": req.user_id,
            "topic": req.topic,
            "content": content,
            "status": "pending",
            "niche": req.niche,
            "source": "api",
        }
    ).execute()

    log.info("Generated post %s for topic '%s'", post_id, req.topic)
    return {"post_id": post_id, "content": content, "status": "pending"}


@app.post("/approve")
def approve_post(req: ApprovalRequest):
    """Approve or reject a pending post."""
    new_status = "approved" if req.approved else "rejected"
    result = (
        supabase.table("posts")
        .update({"status": new_status})
        .eq("id", req.post_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Post not found")
    log.info("Post %s → %s", req.post_id, new_status)
    return {"post_id": req.post_id, "status": new_status}


@app.post("/post-to-linkedin/{post_id}")
async def post_to_linkedin(post_id: str, bg: BackgroundTasks):
    """Trigger Playwright posting for an approved post."""
    row = (
        supabase.table("posts")
        .select("*")
        .eq("id", post_id)
        .single()
        .execute()
    )
    if not row.data:
        raise HTTPException(404, "Post not found")
    if row.data["status"] != "approved":
        raise HTTPException(400, f"Post status is '{row.data['status']}', must be 'approved'")

    bg.add_task(_do_post, post_id, row.data["content"])
    return {"message": "Posting queued", "post_id": post_id}


async def _do_post(post_id: str, content: str):
    """Background task: run Playwright poster, update DB on result."""
    try:
        from linkedin_poster import post_to_linkedin as playwright_post
        success = await asyncio.to_thread(playwright_post, content)
        status = "posted" if success else "failed"
    except Exception as e:
        log.error("Playwright error for %s: %s", post_id, e)
        status = "failed"

    update = {"status": status}
    if status == "posted":
        update["posted_at"] = datetime.utcnow().isoformat()

    supabase.table("posts").update(update).eq("id", post_id).execute()
    log.info("Post %s final status: %s", post_id, status)


@app.get("/posts")
def list_posts(status: str = None, limit: int = 20, user_id: str = "default"):
    """List posts, optionally filtered by status."""
    q = supabase.table("posts").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    return q.order("created_at", desc=True).limit(limit).execute().data


@app.get("/analytics")
def get_analytics(limit: int = 20):
    """Return analytics joined with post topic."""
    return (
        supabase.table("analytics")
        .select("*, posts(topic, content)")
        .order("fetched_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


@app.delete("/posts/{post_id}")
def delete_post(post_id: str):
    supabase.table("posts").delete().eq("id", post_id).execute()
    return {"deleted": post_id}
