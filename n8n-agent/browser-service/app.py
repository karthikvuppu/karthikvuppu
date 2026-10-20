"""Browser service for the n8n agent. n8n calls it over HTTP on the internal docker network.

Safety:
- X-API-Key required on every call.
- Navigation is limited to public internet hosts (no localhost, docker-network or cloud-metadata addresses).
- Password / payment fields can never be filled.
- /submit (irreversible clicks) additionally needs X-Approval-Token, which only the
  approval-gated n8n workflow knows.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright

API_KEY = os.environ["BROWSER_API_KEY"]
APPROVAL_TOKEN = os.environ["BROWSER_APPROVAL_TOKEN"]
PROFILE = os.getenv("BROWSER_PROFILE_DIR", "/data/profile")
HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"
MAX_TEXT = 12000

app = FastAPI(title="agent-browser")
_lock = asyncio.Lock()  # one browser action at a time
_state: dict = {}


def auth(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(401, "bad api key")


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def check_url(url: str):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "only http(s) URLs are allowed")
    if not await asyncio.to_thread(_public_host, p.hostname):
        raise HTTPException(400, "blocked: host is not a public internet address")


async def page():
    if "page" not in _state or _state["page"].is_closed():
        if "ctx" not in _state:
            pw = await async_playwright().start()
            ctx = await pw.chromium.launch_persistent_context(
                PROFILE, headless=HEADLESS, args=["--no-sandbox"], viewport={"width": 1280, "height": 900}
            )

            async def guard(route):
                req = route.request
                if req.is_navigation_request():
                    host = urlparse(req.url).hostname or ""
                    if urlparse(req.url).scheme in ("http", "https") and not await asyncio.to_thread(_public_host, host):
                        await route.abort()
                        return
                await route.continue_()

            await ctx.route("**/*", guard)
            _state.update(pw=pw, ctx=ctx)
        ctx = _state["ctx"]
        _state["page"] = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return _state["page"]


def locator(p, target: str):
    css_like = any(c in target for c in "#.[]>=:")
    return p.locator(target).first if css_like else p.get_by_text(target, exact=False).first


class Goto(BaseModel):
    url: str


class Target(BaseModel):
    target: str


class Fill(BaseModel):
    target: str
    value: str


class Submit(BaseModel):
    target: str
    what_it_does: str = ""


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/goto", dependencies=[Depends(auth)])
async def goto(b: Goto):
    await check_url(b.url)
    async with _lock:
        p = await page()
        await p.goto(b.url, wait_until="domcontentloaded", timeout=45000)
        return {"result": f"Opened {p.url} | title: {await p.title()}"}


@app.get("/text", dependencies=[Depends(auth)])
async def text():
    async with _lock:
        p = await page()
        t = await p.inner_text("body")
        return {"url": p.url, "result": t[:MAX_TEXT] + ("\n...[truncated]" if len(t) > MAX_TEXT else "")}


@app.get("/links", dependencies=[Depends(auth)])
async def links():
    async with _lock:
        p = await page()
        items = await p.eval_on_selector_all(
            "a, button, input, textarea, select",
            """els => els.slice(0, 120).map(e => {
                 const label = (e.innerText || e.value || e.placeholder || e.name || e.getAttribute('aria-label') || '').trim().slice(0, 60);
                 return e.tagName.toLowerCase() + (e.type ? '[' + e.type + ']' : '') + ' | ' + label + ' | ' + (e.href || e.id || '');
               })""",
        )
        return {"url": p.url, "result": "\n".join(items)}


@app.post("/click", dependencies=[Depends(auth)])
async def click(b: Target):
    """Non-irreversible clicks only (navigation, tabs, expanders)."""
    async with _lock:
        p = await page()
        await locator(p, b.target).click(timeout=15000)
        await p.wait_for_load_state("domcontentloaded")
        return {"result": f"Clicked. Now at {p.url}"}


@app.post("/fill", dependencies=[Depends(auth)])
async def fill(b: Fill):
    async with _lock:
        p = await page()
        loc = p.locator(b.target).first if any(c in b.target for c in "#.[]>=:") else p.get_by_label(b.target).first
        info = await loc.evaluate("e => ({t: e.type || '', a: e.autocomplete || ''})")
        if info["t"] == "password" or info["a"].startswith("cc-"):
            raise HTTPException(400, "refused: password/payment fields must be filled by the owner")
        await loc.fill(b.value, timeout=15000)
        return {"result": "Filled."}


@app.post("/submit", dependencies=[Depends(auth)])
async def submit(b: Submit, x_approval_token: str = Header(default="")):
    if x_approval_token != APPROVAL_TOKEN:
        raise HTTPException(403, "approval token required")
    async with _lock:
        p = await page()
        await locator(p, b.target).click(timeout=15000)
        await p.wait_for_load_state("domcontentloaded")
        return {"result": f"Submitted. Now at {p.url}"}
