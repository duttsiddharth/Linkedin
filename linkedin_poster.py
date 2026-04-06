# ─────────────────────────────────────────────────────────────
#  linkedin_poster.py  |  Playwright Posting Engine (Stealth)
#  Fixes from original:
#    ✅ Cookie-based auth (avoids login detection)
#    ✅ Human-like typing delays (randomised)
#    ✅ Proper selector targeting (original was fragile)
#    ✅ Retry logic with exponential backoff
#    ✅ Screenshot on failure for debugging
#    ✅ Headless=True for server deployment
# ─────────────────────────────────────────────────────────────
import os, json, time, random, logging
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

log = logging.getLogger(__name__)

EMAIL    = os.getenv("LI_EMAIL", "")
PASSWORD = os.getenv("LI_PASSWORD", "")
COOKIE_FILE = Path("li_cookies.json")

# ── Human-like typing ─────────────────────────────────────────
def human_type(locator, text: str, wpm: int = 200):
    """Type text at human-like speed with random micro-pauses."""
    chars_per_sec = (wpm * 5) / 60          # avg 5 chars/word
    delay_ms = int(1000 / chars_per_sec)
    for char in text:
        locator.type(char, delay=delay_ms + random.randint(-20, 40))
        if random.random() < 0.02:           # 2% chance of a brief pause
            time.sleep(random.uniform(0.3, 0.8))


# ── Cookie management ─────────────────────────────────────────
def save_cookies(ctx):
    cookies = ctx.cookies()
    COOKIE_FILE.write_text(json.dumps(cookies))
    log.info("Cookies saved (%d cookies)", len(cookies))

def load_cookies(ctx) -> bool:
    if not COOKIE_FILE.exists():
        return False
    cookies = json.loads(COOKIE_FILE.read_text())
    ctx.add_cookies(cookies)
    log.info("Loaded %d cookies from file", len(cookies))
    return True


# ── Login (only when no cookies) ─────────────────────────────
def do_login(page, ctx):
    log.info("Logging in to LinkedIn …")
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    page.wait_for_selector('input[name="session_key"]', timeout=15000)

    page.fill('input[name="session_key"]', EMAIL)
    time.sleep(random.uniform(0.4, 0.9))
    page.fill('input[name="session_password"]', PASSWORD)
    time.sleep(random.uniform(0.3, 0.7))
    page.click('button[type="submit"]')

    # Wait for feed — 2FA may be needed interactively on first run
    try:
        page.wait_for_url("**/feed**", timeout=30000)
    except PWTimeout:
        raise RuntimeError(
            "Login failed or 2FA required. "
            "Run once with headless=False to complete 2FA, then cookies are saved."
        )

    save_cookies(ctx)
    log.info("Login successful, cookies saved.")


# ── Core posting logic ────────────────────────────────────────
def _post(page, content: str) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    time.sleep(random.uniform(2.5, 4.5))

    # Open composer — multiple possible selectors (LinkedIn changes these)
    composer_selectors = [
        "button.share-box-feed-entry__trigger",
        "[data-control-name='share.sharebox_click']",
        "div.share-creation-state__trigger-btn",
        "text=Start a post",
    ]
    opened = False
    for sel in composer_selectors:
        try:
            page.click(sel, timeout=5000)
            opened = True
            break
        except Exception:
            continue

    if not opened:
        page.screenshot(path="debug_composer_open.png")
        raise RuntimeError("Could not open LinkedIn post composer. See debug_composer_open.png")

    # Wait for editor
    editor = page.locator("div.ql-editor").first
    try:
        editor.wait_for(timeout=10000)
    except PWTimeout:
        page.screenshot(path="debug_editor.png")
        raise RuntimeError("Post editor did not appear. See debug_editor.png")

    time.sleep(random.uniform(0.8, 1.5))
    editor.click()
    human_type(editor, content)
    time.sleep(random.uniform(1.5, 3.0))

    # Submit
    post_btn_selectors = [
        "button.share-actions__primary-action",
        "button:has-text('Post')",
        "[data-control-name='share.post']",
    ]
    posted = False
    for sel in post_btn_selectors:
        try:
            page.click(sel, timeout=5000)
            posted = True
            break
        except Exception:
            continue

    if not posted:
        page.screenshot(path="debug_post_btn.png")
        raise RuntimeError("Could not click Post button. See debug_post_btn.png")

    time.sleep(random.uniform(3.0, 5.0))
    log.info("Post submitted successfully.")
    return True


# ── Public entry point (called from FastAPI) ──────────────────
def post_to_linkedin(content: str, retries: int = 2) -> bool:
    if not content or len(content) < 20:
        raise ValueError("Content is too short to post.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = ctx.new_page()

        # Mask webdriver flag
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        cookie_loaded = load_cookies(ctx)

        if cookie_loaded:
            # Verify cookies are still valid
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            if "login" in page.url:
                log.warning("Cookies expired, re-logging in …")
                COOKIE_FILE.unlink(missing_ok=True)
                do_login(page, ctx)
        else:
            do_login(page, ctx)

        for attempt in range(1, retries + 2):
            try:
                result = _post(page, content)
                browser.close()
                return result
            except Exception as e:
                log.error("Posting attempt %d failed: %s", attempt, e)
                if attempt <= retries:
                    wait = 2 ** attempt + random.uniform(0, 2)
                    log.info("Retrying in %.1f seconds …", wait)
                    time.sleep(wait)

        browser.close()
        return False


# ── Local test ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    test_text = sys.argv[1] if len(sys.argv) > 1 else "Test post from AI system."
    print("Posting:", test_text[:60], "…")
    ok = post_to_linkedin(test_text)
    print("Result:", "✅ Posted" if ok else "❌ Failed")
