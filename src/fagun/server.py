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
from . import format as fmt
from . import healing
from . import testdata as _testdata
from .a11y import audit as _a11y_audit
from .advsec import advanced_scan as _advanced_scan
from .browser import launch_debuggable_chrome, manager
from .forms import fuzz_forms as _fuzz_forms
from .security import security_scan as _security_scan
from .vitals import measure as _measure
from .qa import check_links as _check_links
from .qa import crawl as _crawl
from .qa import deep_test as _deep_test
from .qa import run_qa as _run_qa
from .qa import security_headers as _security_headers
from .qa import test_forms as _test_forms
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
- `run QA on <url>` — console errors, failed requests, WCAG a11y, perf, SEO
- `check links on <url>` — find broken links
- `test forms on <url>` — static form security / validation / a11y (no submit)
- `fuzz forms on <url>` — active: fills every field with valid/invalid/edge/
  boundary/out-of-box/injection data, reports real validation gaps
- `perf audit <url>` — real Core Web Vitals + Lighthouse-style score
- `a11y audit <url>` — deep WCAG 2.1 incl. real color contrast
- `security headers of <url>` — CSP, HSTS, X-Frame, info leaks
- `security scan <url>` — full: exposed files, secrets, CORS, XSS, redirect,
  SQLi, CSP, clickjacking, HTTP methods, CRLF, LFI, SSTI, cmdi, GraphQL, more
- `advanced security <url>` — advanced probe battery only
- `list test data <type>` — see the test-case catalog fuzz_forms uses
- `deep test <url>` — crawl + QA + forms + full security + vitals, one report
- `write the report to <path>`

**Power / self-healing**
- `connect to my Chrome` — auto-launches debuggable Chrome, no manual setup
- `browser_exec <python>` — I write any missing automation against the live page
- `save/list/load helper` — reusable snippets that make me smarter each run

Tell me a URL to start. Example: *"deep test https://example.com and write the report to ./report.md."*
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
async def get_console(only_errors: bool = False, limit: int = 50) -> str:
    """Return captured console messages (most recent first, token-capped)."""
    entries = manager.console
    if only_errors:
        entries = [c for c in entries if c.type == "error"]
    if not entries:
        return "No console messages captured."
    cap = min(limit, 200) if fmt.is_terse() else limit
    shown = entries[-cap:]
    lines = [f"{c.type[:4]} {fmt.clip(c.text, 140)}" for c in shown]
    if len(entries) > cap:
        lines.insert(0, f"({len(entries)} total, showing last {cap})")
    return "\n".join(lines)


@mcp.tool()
async def get_network(only_problems: bool = False, limit: int = 60) -> str:
    """Return captured network requests. only_problems -> failures / 4xx / 5xx."""
    entries = manager.network
    if only_problems:
        entries = [n for n in entries if n.failure or (n.status and n.status >= 400)]
    if not entries:
        return "No network activity matched."
    cap = min(limit, 200) if fmt.is_terse() else limit
    shown = entries[-cap:]
    out = [f"{n.method} {n.failure or n.status} {fmt.clip(n.url, 90)}" for n in shown]
    if len(entries) > cap:
        out.insert(0, f"({len(entries)} total, showing last {cap})")
    return "\n".join(out)


@mcp.tool()
async def close_browser() -> str:
    """Close the browser and free resources."""
    return await manager.stop()


# --------------------------------------------------------------------- qa tools
# All QA tools default to TERSE output (compact text) to save the AI's tokens.
# Pass verbose=True for full JSON.
@mcp.tool()
async def crawl(url: str, max_pages: int = 20, verbose: bool = False) -> str:
    """Crawl a site within the same host, up to max_pages."""
    r = await _crawl(url, max_pages)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    lines = [f"crawled {r['crawled']} pages from {url}:"]
    for p in r["pages"]:
        lines.append(f"{p.get('status', 'ERR')} {fmt.clip(p['url'], 90)}")
    return "\n".join(lines)


@mcp.tool()
async def run_qa(url: str, verbose: bool = False) -> str:
    """Run the QA sweep on a single page (console, network, a11y, perf, SEO)."""
    return fmt.render_qa(await _run_qa(url), terse=not verbose and fmt.is_terse())


@mcp.tool()
async def full_qa_sweep(url: str, max_pages: int = 10, report_path: Optional[str] = None) -> str:
    """Crawl a site, run QA on each page, and (optionally) write a Markdown report."""
    crawl_result = await _crawl(url, max_pages)
    results = []
    for p in crawl_result["pages"]:
        if p.get("status") and p["status"] < 400 and not p.get("error"):
            results.append(await _run_qa(p["url"]))
    if report_path:
        md = build_markdown(results, title=f"Fagun QA Report — {url}")
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        return f"Report → {report_path}\n" + fmt.render_multi(results, fmt.is_terse(), f"QA sweep {url}")
    return fmt.render_multi(results, fmt.is_terse(), f"QA sweep {url}")


@mcp.tool()
async def security_headers(url: str, verbose: bool = False) -> str:
    """Check a page for missing/weak security headers (CSP, HSTS, X-Frame, etc.)."""
    r = await _security_headers(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"status {r.get('status', '?')}")


@mcp.tool()
async def check_links(url: str, max_links: int = 100, verbose: bool = False) -> str:
    """Find broken links (4xx/5xx/unreachable) among the links on a page."""
    r = await _check_links(url, max_links)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"{r.get('links_checked', 0)} checked")


@mcp.tool()
async def test_forms(url: str, verbose: bool = False) -> str:
    """Audit every form on a page for security, validation and a11y issues (no submit)."""
    r = await _test_forms(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"{r.get('forms', 0)} forms")


@mcp.tool()
async def deep_test(url: str, max_pages: int = 8, report_path: Optional[str] = None,
                    security: bool = True, perf: bool = True, verbose: bool = False) -> str:
    """Full site audit: crawl + per-page QA (console/network/WCAG a11y/SEO) + form
    audit + full security battery + real Core Web Vitals. One aggregated report.
    Every finding is evidence-backed. security/perf toggle the heavy passes."""
    result = await _deep_test(url, max_pages, security=security, perf=perf)
    if report_path:
        md = build_markdown(result["results"], title=f"Fagun Deep Test — {url}")
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        prefix = f"Report → {report_path}\n"
    else:
        prefix = ""
    if verbose:
        return prefix + fmt.dumps(result)
    return prefix + fmt.render_multi(result["results"], fmt.is_terse(), f"Deep test {url}")


@mcp.tool()
async def security_scan(url: str, advanced: bool = True, verbose: bool = False) -> str:
    """Active-but-safe security scan. Core: exposed files, leaked secrets, CORS,
    cookie flags, reflected-XSS, open redirect, SQLi error signals. With
    advanced=True (default) also: CSP quality, clickjacking, risky HTTP methods,
    mixed content, missing SRI, sensitive-page caching, host-header injection,
    CRLF, path-traversal/LFI, SSTI, command-injection signals, GraphQL
    introspection, error/stack-trace disclosure, sensitive data in URL.
    NON-DESTRUCTIVE, every finding evidence-backed. Authorized targets only."""
    r = await _security_scan(url)
    findings = list(r.get("findings", []))
    if advanced:
        try:
            findings.extend((await _advanced_scan(url)).get("findings", []))
        except Exception as e:
            findings.append({"severity": "low", "type": "scan-error", "detail": f"advanced: {e}"})
    seen: set = set()
    uniq = []
    for f in findings:
        k = (f.get("type"), f.get("detail"))
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    r = {"url": url, "findings": uniq}
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, uniq, meta="security scan")


@mcp.tool()
async def advanced_security(url: str, verbose: bool = False) -> str:
    """Advanced security probes only (CSP/clickjacking/HTTP-methods/mixed-content/
    SRI/cache/host-header/CRLF/path-traversal/SSTI/cmdi/GraphQL/error-disclosure).
    Non-destructive, evidence-backed. Authorized targets only."""
    r = await _advanced_scan(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta="advanced security")


@mcp.tool()
async def perf_audit(url: str, verbose: bool = False) -> str:
    """Measure REAL Core Web Vitals (LCP, CLS, TBT, FCP, TTFB, INP) via the
    browser's Performance APIs and return a Lighthouse-comparable perf score
    (0-100). No estimates — every number is measured."""
    r = await _measure(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    m = r["metrics"]
    head = (f"{url} | perf score {r['score']}/100 | "
            f"LCP {m.get('LCP')}ms CLS {m.get('CLS')} TBT {m.get('TBT')}ms "
            f"FCP {m.get('FCP')}ms TTFB {m.get('TTFB')}ms")
    return head + "\n" + fmt.findings_block(url, r.get("findings", []), meta="vitals")


@mcp.tool()
async def a11y_audit(url: str, verbose: bool = False) -> str:
    """Deep accessibility audit — real WCAG 2.1 checks in the live DOM including
    computed color-contrast, labels, ARIA roles, headings, focus order, zoom.
    Findings include example selectors as evidence."""
    r = await _a11y_audit(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps({k: v for k, v in r.items() if k != "raw"})
    return fmt.findings_block(url, r.get("findings", []), meta="a11y (WCAG)")


@mcp.tool()
async def fuzz_forms(url: str, submit: bool = False, verbose: bool = False) -> str:
    """Actively fuzz every form field with labelled test data (valid/invalid/edge/
    boundary/out-of-box/injection) and report REAL validation gaps read from the
    browser's Constraint Validation API. Default does NOT submit; submit=True also
    submits crafted input once (authorized targets only)."""
    r = await _fuzz_forms(url, submit=submit)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    meta = f"{r.get('forms', 0)} forms, {r.get('cases_tested', 0)} cases"
    return fmt.findings_block(url, r.get("findings", []), meta=meta)


@mcp.tool()
def list_test_data(field_type: str = "text", name: str = "") -> str:
    """Show the labelled test-data catalog that fuzz_forms uses for a field type
    (email/number/tel/url/date/password/text). Categories: valid, invalid, edge,
    boundary, outofbox, injection."""
    cases = _testdata.cases_for(field_type, name)
    lines = [f"{len(cases)} test cases for type={field_type!r} name={name!r}:"]
    for c in cases:
        lines.append(f"[{c.category}] {c.label}: {fmt.clip(c.value, 50)!r}")
    return "\n".join(lines)


# ------------------------------------------------- self-healing / power tools
@mcp.tool()
async def browser_exec(code: str) -> str:
    """Run async Python against the live page (`page`, `context`, `manager` in scope;
    assign `result` or return a value). Use when a built-in tool can't do what you
    need — write the missing automation directly. Runs locally on this machine."""
    return await healing.browser_exec(code)


@mcp.tool()
async def save_helper(name: str, code: str) -> str:
    """Persist a reusable browser helper snippet so it's available next session."""
    return healing.save_helper(name, code)


@mcp.tool()
async def list_helpers() -> str:
    """List saved helper snippets."""
    return healing.list_helpers()


@mcp.tool()
async def load_helper(name: str) -> str:
    """Show the code of a saved helper."""
    return healing.load_helper(name)


@mcp.tool()
async def connect_chrome(port: int = 9222) -> str:
    """Launch YOUR real Chrome with remote debugging on and attach to it — fully
    automatic, no manual chrome://inspect step. Uses a dedicated Fagun profile."""
    cdp = launch_debuggable_chrome(port)
    await manager.stop()
    msg = await manager.start()
    return f"Chrome launched with debugging at {cdp}. {msg}"


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
