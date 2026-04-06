# ─────────────────────────────────────────────────────────────
#  app.py  |  LinkedIn AI Ghostwriter — Streamlit Dashboard
#  Run: streamlit run app.py
# ─────────────────────────────────────────────────────────────
import os, requests, time
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

API  = os.getenv("API_BASE_URL", "http://localhost:8000")
sb   = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

st.set_page_config(
    page_title="LinkedIn AI Ghostwriter",
    page_icon="✍️",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────
st.sidebar.title("✍️ LinkedIn AI Ghostwriter")
page = st.sidebar.radio("Navigate", ["Generate", "Queue", "Analytics"])
st.sidebar.divider()
st.sidebar.caption("Powered by Gemini 1.5 Flash · Supabase · Playwright")

# ── Status badges ─────────────────────────────────────────────
STATUS_COLOR = {
    "pending":  "🟡",
    "approved": "🟢",
    "rejected": "🔴",
    "posted":   "✅",
    "failed":   "❌",
}

# ════════════════════════════════════════════════════════════════
#  PAGE: GENERATE
# ════════════════════════════════════════════════════════════════
if page == "Generate":
    st.title("Generate a LinkedIn Post")

    with st.form("gen_form"):
        col1, col2 = st.columns([2, 1])
        topic = col1.text_input(
            "Topic",
            placeholder="The future of AI agents in enterprise data teams",
        )
        niche = col2.selectbox(
            "Niche",
            ["AI & Data Engineering", "Product Management", "Leadership",
             "SaaS & Startups", "Cloud & DevOps", "Finance & FinTech"],
        )
        tone = st.select_slider(
            "Tone",
            options=["Professional", "Balanced", "Bold & Contrarian"],
            value="Bold & Contrarian",
        )
        tone_map = {
            "Professional": "professional, authoritative, data-driven",
            "Balanced": "insightful, clear, evidence-based",
            "Bold & Contrarian": "bold, insightful, slightly controversial",
        }
        submitted = st.form_submit_button("✨ Generate Post", use_container_width=True)

    if submitted:
        if not topic.strip():
            st.error("Please enter a topic.")
        else:
            with st.spinner("Generating your post with Gemini …"):
                try:
                    r = requests.post(
                        f"{API}/generate",
                        json={"topic": topic, "niche": niche, "tone": tone_map[tone]},
                        timeout=40,
                    )
                    data = r.json()
                except Exception as e:
                    st.error(f"API error: {e}")
                    st.stop()

            if r.status_code == 409:
                st.warning(f"⚠️ {data.get('detail', 'Duplicate topic')} — try a variation.")
                st.stop()
            elif r.status_code != 200:
                st.error(f"Error {r.status_code}: {data.get('detail', 'Unknown error')}")
                st.stop()
            else:
                st.session_state["last_post"] = data
                st.success("Post generated!")

    if "last_post" in st.session_state:
        post = st.session_state["last_post"]
        st.subheader("Preview")
        content = st.text_area(
            "Edit before approving:",
            value=post["content"],
            height=300,
            key="post_content_edit",
        )
        st.caption(f"Post ID: `{post['post_id']}`  |  Characters: {len(content)}")

        col_a, col_b, col_c = st.columns(3)
        if col_a.button("✅ Approve & Queue", use_container_width=True):
            requests.post(
                f"{API}/approve",
                json={"post_id": post["post_id"], "approved": True},
                timeout=10,
            )
            st.success("Approved! Post is queued.")
            del st.session_state["last_post"]

        if col_b.button("🚀 Approve & Post Now", use_container_width=True):
            requests.post(
                f"{API}/approve",
                json={"post_id": post["post_id"], "approved": True},
                timeout=10,
            )
            with st.spinner("Posting to LinkedIn via Playwright …"):
                r2 = requests.post(
                    f"{API}/post-to-linkedin/{post['post_id']}",
                    timeout=70,
                )
            if r2.status_code == 200:
                st.success("🎉 Posted to LinkedIn!")
            else:
                st.error("Posting failed. Check server logs.")
            del st.session_state["last_post"]

        if col_c.button("❌ Reject", use_container_width=True):
            requests.post(
                f"{API}/approve",
                json={"post_id": post["post_id"], "approved": False},
                timeout=10,
            )
            st.warning("Rejected and logged.")
            del st.session_state["last_post"]


# ════════════════════════════════════════════════════════════════
#  PAGE: QUEUE
# ════════════════════════════════════════════════════════════════
elif page == "Queue":
    st.title("Post Queue")
    status_filter = st.selectbox(
        "Filter by status", ["all", "pending", "approved", "posted", "rejected", "failed"]
    )

    try:
        params = {} if status_filter == "all" else {"status": status_filter}
        posts = requests.get(f"{API}/posts", params={**params, "limit": 50}, timeout=10).json()
    except Exception as e:
        st.error(f"Could not fetch posts: {e}")
        st.stop()

    if not posts:
        st.info("No posts found.")
    else:
        for p in posts:
            icon = STATUS_COLOR.get(p["status"], "⚪")
            with st.expander(f"{icon} [{p['status'].upper()}] {p['topic']} — {p['created_at'][:10]}"):
                st.write(p["content"])
                col1, col2 = st.columns(2)
                if p["status"] == "approved":
                    if col1.button("🚀 Post Now", key=f"post_{p['id']}"):
                        with st.spinner("Posting …"):
                            requests.post(f"{API}/post-to-linkedin/{p['id']}", timeout=70)
                        st.success("Posted!")
                        time.sleep(1)
                        st.rerun()
                if p["status"] in ("pending", "approved"):
                    if col2.button("❌ Reject", key=f"reject_{p['id']}"):
                        requests.post(
                            f"{API}/approve",
                            json={"post_id": p["id"], "approved": False},
                            timeout=10,
                        )
                        st.rerun()


# ════════════════════════════════════════════════════════════════
#  PAGE: ANALYTICS
# ════════════════════════════════════════════════════════════════
elif page == "Analytics":
    st.title("Analytics")

    # Summary KPIs from Supabase
    posts_data = sb.table("posts").select("status").execute().data
    total     = len(posts_data)
    posted    = sum(1 for p in posts_data if p["status"] == "posted")
    pending   = sum(1 for p in posts_data if p["status"] == "pending")
    rejected  = sum(1 for p in posts_data if p["status"] == "rejected")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Generated", total)
    k2.metric("Posted", posted)
    k3.metric("Pending Approval", pending)
    k4.metric("Rejected", rejected)

    st.divider()
    st.subheader("Engagement (last 20 posts)")

    try:
        analytics = requests.get(f"{API}/analytics", params={"limit": 20}, timeout=10).json()
    except Exception:
        analytics = []

    if analytics:
        import pandas as pd
        df = pd.DataFrame(analytics)
        if not df.empty:
            st.dataframe(
                df[["post_id", "impressions", "likes", "comments", "shares", "engagement_r"]],
                use_container_width=True,
            )
    else:
        st.info("No analytics data yet. Analytics are fetched daily after posting.")
