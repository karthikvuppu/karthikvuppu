"""Sign in to the sites you want the agent to use, once, on your own computer.

    pip install playwright && playwright install chromium
    python browser-service/login.py https://mail.google.com https://example.com

A visible browser opens using the SAME profile folder the agent uses (./data/browser_profile).
Log in, then close the window. The agent keeps those sessions. Stop the stack first
(docker compose stop browser) so two browsers don't use the profile at once.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

profile = Path(__file__).resolve().parent.parent / "data" / "browser_profile"
profile.mkdir(parents=True, exist_ok=True)
urls = sys.argv[1:] or ["https://accounts.google.com"]

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(str(profile), headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    for i, u in enumerate(urls):
        (page if i == 0 else ctx.new_page()).goto(u)
    print("Log in, then close the browser window to finish.")
    try:
        ctx.wait_for_event("close", timeout=0)
    except Exception:
        pass
