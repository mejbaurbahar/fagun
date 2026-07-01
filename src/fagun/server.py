"""Fagun MCP server.

Exposes browser-driving + QA tools over MCP so ANY MCP-capable AI tool
(Claude Code/Desktop, Cursor, Codex, Antigravity, Windsurf, Cline, VS Code)
can use them. The `fagun` prompt is the entry point users invoke.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import __version__
from .browser import manager
from .qa import crawl as _crawl
from .qa import run_qa as _run_qa
from .report import build_markdown

mcp = FastMCP("fagun")

MENU = f"""🦊 **Fagun v{__version__}** — browser + QA agent, ready.

I can drive a real browser and run a full quality sweep. Ask me to:

**Browse & debug**
- `open the browser` / `go to <url>`
- `click <text>` · `type <text> into <field>` · `press Enter`
- `screenshot` · `show console errors` · `show network requests`
- `run this JS: <code>`

**QA & bug hunting**
- `crawl <url>` — map the site
- `run QA on <url>` — console errors, failed requests, a11y, perf, SEO
- `full QA sweep of <url>` — crawl then QA every page
- `write the report to <path>`

Tell me a URL to start. Example: *"run a full QA sweep of https://example.com and write the report."*
"""


@mcp.prompt(title="Start Fagun")
def fagun() -> str:
    """Entry point. Invoke this to start Fagun and see what it can do."""
    return MENU


@mcp.tool()
def fagun_start() -> str:
    """Start Fagun and list its capabilities. Call this when the user says 'fagun'."""
    return MENU


# ---------------------------------------------------------------- browser tools
@mcp.tool()
async def open_browser(headless: bool = True) -> str:
    """Launch (or attach to) the browser."""
    return await manager.start(headless=headless)


@mcp.tool()
async def navigate(url: str) -> str:
    """Go to a URL."""
    page = await manager.page()
    resp = await page.goto(url, wait_until="load", timeout=30000)
    return f"Loaded {page.url} (status {resp.status if resp else '?'}) — title: {await page.title()!r}"


@mcp.tool()
async def click(target: str) -> str:
    """Click an element by CSS selector or visible text."""
    page = await manager.page()
    try:
        await page.click(target, timeout=8000)
    except Exception:
        await page.get_by_text(target, exact=False).first.click(timeout=8000)
    return f"Clicked {target!r}. Now at {page.url}"


@mcp.tool()
async def fill(selector: str, value: str) -> str:
    """Type text into a form field (CSS selector or label/placeholder text)."""
    page = await manager.page()
    try:
        await page.fill(selector, value, timeout=8000)
    except Exception:
        await page.get_by_label(selector).fill(value, timeout=8000)
    return f"Filled {selector!r}."


@mcp.tool()
async def press_key(key: str) -> str:
    """Press a keyboard key, e.g. 'Enter', 'Tab', 'Escape'."""
    page = await manager.page()
    await page.keyboard.press(key)
    return f"Pressed {key}."


@mcp.tool()
async def screenshot(full_page: bool = False) -> str:
    """Take a screenshot; saves a PNG and returns its path."""
    page = await manager.page()
    path = os.path.join(tempfile.gettempdir(), f"fagun-{abs(hash(page.url)) % 10**6}.png")
    await page.screenshot(path=path, full_page=full_page)
    return f"Screenshot saved: {path}"


@mcp.tool()
async def evaluate_js(code: str) -> str:
    """Run JavaScript in the page and return the result as JSON."""
    page = await manager.page()
    result = await page.evaluate(code)
    try:
        return json.dumps(result, default=str)[:5000]
    except Exception:
        return str(result)[:5000]


@mcp.tool()
async def get_console(only_errors: bool = False) -> str:
    """Return captured console messages."""
    entries = manager.console
    if only_errors:
        entries = [c for c in entries if c.type == "error"]
    if not entries:
        return "No console messages captured."
    return "\n".join(f"[{c.type}] {c.text} ({c.location})" for c in entries[-100:])


@mcp.tool()
async def get_network(only_problems: bool = False) -> str:
    """Return captured network requests. only_problems -> failures / 4xx / 5xx."""
    entries = manager.network
    if only_problems:
        entries = [n for n in entries if n.failure or (n.status and n.status >= 400)]
    if not entries:
        return "No network activity matched."
    out = []
    for n in entries[-150:]:
        state = n.failure or n.status
        out.append(f"{n.method} {state} [{n.resource_type}] {n.url}")
    return "\n".join(out)


@mcp.tool()
async def close_browser() -> str:
    """Close the browser and free resources."""
    return await manager.stop()


# --------------------------------------------------------------------- qa tools
@mcp.tool()
async def crawl(url: str, max_pages: int = 20) -> str:
    """Crawl a site within the same host, up to max_pages. Returns JSON."""
    return json.dumps(await _crawl(url, max_pages), indent=2)


@mcp.tool()
async def run_qa(url: str) -> str:
    """Run the QA sweep on a single page (console, network, a11y, perf, SEO)."""
    return json.dumps(await _run_qa(url), indent=2)


@mcp.tool()
async def full_qa_sweep(url: str, max_pages: int = 10, report_path: Optional[str] = None) -> str:
    """Crawl a site, run QA on each page, and (optionally) write a Markdown report."""
    crawl_result = await _crawl(url, max_pages)
    results = []
    for p in crawl_result["pages"]:
        if p.get("status") and p["status"] < 400 and not p.get("error"):
            results.append(await _run_qa(p["url"]))
    md = build_markdown(results, title=f"Fagun QA Report — {url}")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        return f"Swept {len(results)} pages. Report written to {report_path}\n\n{md[:1500]}"
    return md


@mcp.tool()
async def write_report(results_json: str, path: str, title: str = "Fagun QA Report") -> str:
    """Write a Markdown report from a JSON list of run_qa results."""
    results = json.loads(results_json)
    if isinstance(results, dict):
        results = [results]
    md = build_markdown(results, title=title)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return f"Report written to {path}"


def serve() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    serve()
