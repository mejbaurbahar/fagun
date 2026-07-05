"""Fagun MCP server.

Exposes browser-driving + QA tools over MCP so ANY MCP-capable AI tool
(Claude Code/Desktop, Cursor, Codex, Antigravity, Windsurf, Cline, VS Code)
can use them. The `fagun` prompt is the entry point users invoke.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import tempfile
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import __version__
from . import format as fmt
from . import healing
from . import readiness as _readiness
from . import scope as _scope
from . import session as _session
from . import security_toolkit as _security_toolkit
from . import style as _style
from . import testdata as _testdata
from . import uat as _uat
from .a11y import audit as _a11y_audit
from .advsec import advanced_scan as _advanced_scan
from .browser import launch_debuggable_chrome, manager
from .fingerprint import fingerprint as _fingerprint
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
from .report import write_report as _write_report

mcp = FastMCP("fagun")


def _browser_tool(fn):
    """Wrap a browser-touching tool so calls are (1) scope-guarded on any ``url``
    argument and (2) serialized on the shared browser lock. ``functools.wraps``
    keeps the original signature visible to FastMCP's schema generator (it follows
    ``__wrapped__``), so tool schemas are unchanged."""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            bound = sig.bind_partial(*args, **kwargs)
            url = bound.arguments.get("url")
        except TypeError:
            url = None
        if isinstance(url, str) and url:
            _scope.guard(url)
        async with manager.lock:
            return await fn(*args, **kwargs)

    return wrapper

MENU = f"""🦊 **Fagun v{__version__}** — real-user UAT, QA, security, and readiness.

```
╭────────────────────────────────────────────────────────────╮
│  FAGUN PROCESS                                             │
├────────────────────────────────────────────────────────────┤
│  1. Connect  → real Chrome / Chrome DevTools MCP           │
│  2. Recon    → crawl, fingerprint, map journeys            │
│  3. Act      → use the product like real customers         │
│  4. Hunt     → console, network, forms, a11y, perf, sec    │
│  5. Prove    → evidence, screenshots, vitals, repro steps  │
│  6. Decide   → 16-category readiness verdict + report      │
╰────────────────────────────────────────────────────────────╯
```

Chrome DevTools MCP is configured for `--auto-connect`, so when Chrome asks
**Allow remote debugging?**, click **Allow** to let Fagun/DevTools reuse your
signed-in default Chrome session. That means logged-in dashboards can be tested
without sharing passwords with the AI.

**Fast commands**
- `deep test <url> and save the report to ./fagun-report.html`
- `run QA on <url>` · `check links on <url>` · `test forms on <url>`
- `security scan <url>` · `perf audit <url>` · `a11y audit <url>`
- `emulate mobile` · `keyboard walk <url>` · `run journey <steps>`

**What I check**
`journeys` · `auth/session` · `links` · `console` · `network` · `forms` ·
`validation` · `a11y` · `SEO` · `visual overflow` · `responsive layout` ·
`Core Web Vitals` · `headers/CORS/CSP` · `XSS/redirect/SQLi/LFI/SSTI/cmdi` ·
`secrets/exposed files` · `GraphQL` · `readiness score`

**Token-lean mode**
Use `report_path` for full evidence on disk. Chat stays compact by default.
Set `FAGUN_TERSE=mini` for extra-short summaries in small-context models.

**Fagun Style**
For any AI/model, call `fagun_style_prompt` once and use it as the response
contract. For apps/wrappers, call `fagun_style_schema` and render structured JSON
as cards/panels. Use `fagun_render_response` to convert JSON/plain output into
the same Fagun layout.

**Advanced security orchestration**
Use `fagun_security_prompt` for the enterprise security-testing prompt, then
`list_external_security_tools` / `recommend_security_tools` to plan safe adapters
for Loxs, Shannon, Lonkero, BeeXSS, TimeVault, NextSploit, payload corpora, and
other external tools. Active testing remains authorized-scope only.

Tell me a URL to start. Example:
`fagun deep test https://example.com and save the report to ./report.html`
"""


@mcp.prompt(title="Start Fagun")
def fagun() -> str:
    """Entry point. Invoke this to start Fagun and see what it can do."""
    return MENU


@mcp.tool()
def fagun_start() -> str:
    """Start Fagun and list its capabilities. Call this when the user says 'fagun'."""
    return MENU


@mcp.tool()
def fagun_style_prompt(mode: str = "markdown") -> str:
    """Return Fagun's reusable response-style instruction for any AI model.

    Use mode="markdown" for chat/custom instructions, or mode="json" when a
    wrapper/frontend wants structured output to render as custom cards.
    """
    return _style.style_prompt(mode)


@mcp.tool()
def fagun_style_schema() -> str:
    """Return the JSON schema for Fagun-style structured responses."""
    return _style.schema_json()


@mcp.tool()
def fagun_render_response(response_json_or_text: str, title: str = "Fagun Response") -> str:
    """Render JSON/plain text into Fagun's consistent Markdown panel style."""
    payload = _style.coerce_payload(response_json_or_text, title=title)
    return _style.render_response(payload, title=payload.get("_title", title))


@mcp.tool()
def fagun_security_prompt() -> str:
    """Return Fagun's advanced authorized-security-testing prompt."""
    return _security_toolkit.security_platform_prompt()


@mcp.tool()
def list_external_security_tools(category: str = "") -> str:
    """List Fagun's external security tool catalog, optionally filtered by category/signal."""
    tools = _security_toolkit.list_security_tools(category)
    return _security_toolkit.render_tool_catalog(tools)


@mcp.tool()
def recommend_security_tools(goal: str = "", target_profile_json: str = "") -> str:
    """Recommend external security tools for an authorized goal/target profile."""
    recommendation = _security_toolkit.recommend_security_tools(goal, target_profile_json)
    return _security_toolkit.render_recommendation(recommendation)


# ---------------------------------------------------------------- browser tools
@mcp.tool()
@_browser_tool
async def open_browser(headless: bool = True) -> str:
    """Launch (or attach to) the browser."""
    return await manager.start(headless=headless)


@mcp.tool()
@_browser_tool
async def navigate(url: str) -> str:
    """Go to a URL."""
    page = await manager.page()
    resp = await page.goto(url, wait_until="load", timeout=30000)
    return f"Loaded {page.url} (status {resp.status if resp else '?'}) — title: {await page.title()!r}"


@mcp.tool()
@_browser_tool
async def click(target: str) -> str:
    """Click an element by CSS selector or visible text."""
    page = await manager.page()
    try:
        await page.click(target, timeout=8000)
    except Exception:
        await page.get_by_text(target, exact=False).first.click(timeout=8000)
    return f"Clicked {target!r}. Now at {page.url}"


@mcp.tool()
@_browser_tool
async def fill(selector: str, value: str) -> str:
    """Type text into a form field (CSS selector or label/placeholder text)."""
    page = await manager.page()
    try:
        await page.fill(selector, value, timeout=8000)
    except Exception:
        await page.get_by_label(selector).fill(value, timeout=8000)
    return f"Filled {selector!r}."


@mcp.tool()
@_browser_tool
async def press_key(key: str) -> str:
    """Press a keyboard key, e.g. 'Enter', 'Tab', 'Escape'."""
    page = await manager.page()
    await page.keyboard.press(key)
    return f"Pressed {key}."


@mcp.tool()
@_browser_tool
async def screenshot(full_page: bool = False) -> str:
    """Take a screenshot; saves a PNG and returns its path."""
    page = await manager.page()
    path = os.path.join(tempfile.gettempdir(), f"fagun-{abs(hash(page.url)) % 10**6}.png")
    await page.screenshot(path=path, full_page=full_page)
    return f"Screenshot saved: {path}"


@mcp.tool()
@_browser_tool
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
    entries = list(manager.console)
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
    entries = list(manager.network)
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
@_browser_tool
async def close_browser() -> str:
    """Close the browser and free resources."""
    return await manager.stop()


# --------------------------------------------------------------------- qa tools
# All QA tools default to TERSE output (compact text) to save the AI's tokens.
# Pass verbose=True for full JSON.
@mcp.tool()
@_browser_tool
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
@_browser_tool
async def run_qa(url: str, verbose: bool = False) -> str:
    """Run the QA sweep on a single page (console, network, a11y, perf, SEO)."""
    return fmt.render_qa(await _run_qa(url), terse=not verbose and fmt.is_terse())


@mcp.tool()
@_browser_tool
async def full_qa_sweep(url: str, max_pages: int = 10, report_path: Optional[str] = None) -> str:
    """Crawl a site, run QA on each page, and (optionally) write a Markdown report."""
    crawl_result = await _crawl(url, max_pages)
    results = []
    for p in crawl_result["pages"]:
        if p.get("status") and p["status"] < 400 and not p.get("error"):
            results.append(await _run_qa(p["url"]))
    if report_path:
        sc = _readiness.build_scorecard(results, meta={"target": url})
        _write_report(results, report_path, title=f"Fagun QA Report — {url}", scorecard=sc)
        return f"Report → {report_path}\n" + fmt.render_multi(results, fmt.is_terse(), f"QA sweep {url}")
    return fmt.render_multi(results, fmt.is_terse(), f"QA sweep {url}")


@mcp.tool()
@_browser_tool
async def security_headers(url: str, verbose: bool = False) -> str:
    """Check a page for missing/weak security headers (CSP, HSTS, X-Frame, etc.)."""
    r = await _security_headers(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"status {r.get('status', '?')}")


@mcp.tool()
@_browser_tool
async def check_links(url: str, max_links: int = 100, verbose: bool = False) -> str:
    """Find broken links (4xx/5xx/unreachable) among the links on a page."""
    r = await _check_links(url, max_links)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"{r.get('links_checked', 0)} checked")


@mcp.tool()
@_browser_tool
async def test_forms(url: str, verbose: bool = False) -> str:
    """Audit every form on a page for security, validation and a11y issues (no submit)."""
    r = await _test_forms(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta=f"{r.get('forms', 0)} forms")


@mcp.tool()
@_browser_tool
async def deep_test(url: str, max_pages: int = 8, report_path: Optional[str] = None,
                    security: bool = True, perf: bool = True, keyboard: bool = True,
                    verbose: bool = False) -> str:
    """Full site audit: crawl + per-page QA (console/network/WCAG a11y/SEO) + form
    audit + full security battery + real Core Web Vitals + keyboard reachability,
    then a product-readiness scorecard (category scores + release verdict). One
    aggregated report. Report format follows the file extension: .md / .html /
    .json / .xml(JUnit). Every finding is evidence-backed."""
    result = await _deep_test(url, max_pages, security=security, perf=perf, keyboard=keyboard)
    scorecard = _readiness.build_scorecard(result["results"], meta={"target": url, "pages": result["pages_tested"]})
    prefix = ""
    if report_path:
        _write_report(result["results"], report_path,
                      title=f"Fagun Deep Test — {url}", scorecard=scorecard)
        prefix = f"Report → {report_path}\n"
    verdict = (f"🧭 Readiness: {scorecard['verdict']} ({scorecard['overall_score']}/100) — "
               f"{scorecard['verdict_reason']}\n")
    if verbose:
        return prefix + verdict + fmt.dumps({"result": result, "readiness": scorecard})
    return prefix + verdict + fmt.render_multi(result["results"], fmt.is_terse(), f"Deep test {url}")


@mcp.tool()
@_browser_tool
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
@_browser_tool
async def advanced_security(url: str, verbose: bool = False) -> str:
    """Advanced security probes only (CSP/clickjacking/HTTP-methods/mixed-content/
    SRI/cache/host-header/CRLF/path-traversal/SSTI/cmdi/GraphQL/error-disclosure).
    Non-destructive, evidence-backed. Authorized targets only."""
    r = await _advanced_scan(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    return fmt.findings_block(url, r.get("findings", []), meta="advanced security")


@mcp.tool()
@_browser_tool
async def fingerprint(url: str, verbose: bool = False) -> str:
    """Detect the tech stack of a URL — server/proxy, hosting (Vercel/Netlify/
    Cloudflare/…), JS frameworks (React/Next/Vue/Angular/…), CMS/platform
    (WordPress/Shopify/…), and analytics — from real headers + DOM/JS signals.
    Use it before hunting to tune checks and to give the report context."""
    r = await _fingerprint(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    head = f"{url} | {r['summary']}"
    if r.get("findings"):
        return head + "\n" + fmt.findings_block(url, r["findings"], meta="tech")
    return head


@mcp.tool()
@_browser_tool
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
@_browser_tool
async def a11y_audit(url: str, verbose: bool = False) -> str:
    """Deep accessibility audit — real WCAG 2.1 checks in the live DOM including
    computed color-contrast, labels, ARIA roles, headings, focus order, zoom.
    Findings include example selectors as evidence."""
    r = await _a11y_audit(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps({k: v for k, v in r.items() if k != "raw"})
    return fmt.findings_block(url, r.get("findings", []), meta="a11y (WCAG)")


@mcp.tool()
@_browser_tool
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


# ------------------------------------------------------------- UAT / end-user
@mcp.tool()
def list_personas() -> str:
    """List the end-user personas you can emulate (mobile, slow-internet,
    low-end, keyboard-only, screen-reader, international, dark-mode, …)."""
    return "\n".join(f"{p['name']}: {p['note']}" for p in _uat.list_personas())


@mcp.tool()
@_browser_tool
async def emulate_persona(name: str) -> str:
    """Reconfigure the browser to experience the site AS a given user type — real
    device viewport/touch, network + CPU throttling, and media prefs (reduced
    motion, dark mode, forced colors). Then browse/journey as that user. Personas:
    desktop, first-time, mobile, android-mobile, tablet, slow-internet, low-end,
    keyboard-only, screen-reader, dark-mode, international."""
    r = await _uat.emulate_persona(name)
    if not r.get("ok"):
        return f"{r.get('error')}. Available: {', '.join(r.get('available', []))}"
    return f"Now browsing as '{r['persona']}' — {r['note']}. Applied: {fmt.dumps(r['applied'])}"


@mcp.tool()
@_browser_tool
async def run_journey(steps_json: str, name: str = "journey", screenshots: bool = True,
                      verbose: bool = False) -> str:
    """Walk a complete user journey step-by-step and report whether a real user
    could finish it. steps_json is a JSON list of steps, each:
    {"action": ..., "target"/"url"/"value"/"label": ...}. Actions: goto, click,
    fill, select, press, wait, assert_text, assert_no_text, assert_url,
    assert_visible, screenshot. Captures per-step pass/fail, screenshot, console
    errors, failed requests, and timing. A step 'passes' only if the browser
    actually did it — nothing is faked. See list_journeys for templates."""
    try:
        steps = json.loads(steps_json)
    except Exception as e:
        return f"Could not parse steps_json: {e}"
    if isinstance(steps, dict):
        steps = steps.get("steps", [steps])
    r = await _uat.run_journey(steps, name=name, screenshots=screenshots)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    head = (f"Journey '{r['journey']}': {'✅ COMPLETED' if r['completed'] else '❌ BLOCKED'} "
            f"— {r['passed']}/{r['steps_total']} steps passed")
    lines = [head]
    for s in r["step_log"]:
        mark = "✓" if s["ok"] else "✗"
        extra = []
        if s["console_errors"]:
            extra.append(f"{s['console_errors']} JS err")
        if s["network_failures"]:
            extra.append(f"{s['network_failures']} req fail")
        tail = f" [{', '.join(extra)}]" if extra else ""
        lines.append(f"{mark} {s['i']}. {s['label']} — {fmt.clip(s['detail'], 80)} ({s['ms']}ms){tail}")
    return "\n".join(lines)


@mcp.tool()
def list_journeys() -> str:
    """List built-in user-journey templates (login, register, password-reset,
    search, checkout, contact) you can copy into run_journey and fill in."""
    return "Journey templates (copy + fill selectors/values):\n" + "\n".join(
        f"- {name}: {len(_uat.JOURNEY_TEMPLATES[name])} steps" for name in _uat.list_journeys()
    ) + "\nUse the template JSON as a starting point for run_journey."


@mcp.tool()
def journey_template(name: str) -> str:
    """Return a journey template as JSON so you can edit it and pass to run_journey."""
    tpl = _uat.JOURNEY_TEMPLATES.get(name.strip().lower())
    if not tpl:
        return f"No template {name!r}. Available: {', '.join(_uat.list_journeys())}"
    return fmt.dumps(tpl)


@mcp.tool()
@_browser_tool
async def keyboard_walk(url: str, verbose: bool = False) -> str:
    """Tab through a page like a keyboard-only / screen-reader user. Reports focus
    reachability, missing visible focus indicators, and focus traps — real
    evidence for accessibility + UX readiness."""
    r = await _uat.keyboard_walk(url)
    if verbose or not fmt.is_terse():
        return fmt.dumps(r)
    meta = f"{r['tab_stops']} tab stops / {r['focusable']} focusable"
    return fmt.findings_block(url, r.get("findings", []), meta=meta)


@mcp.tool()
async def readiness_report(results_json: str, report_path: Optional[str] = None,
                           title: str = "Fagun Readiness", verbose: bool = False) -> str:
    """Build a product-readiness scorecard from collected results (JSON list of
    result dicts with 'findings'). Returns 16 category scores (0-100), an overall
    release verdict, and prioritized recommendations (why it matters + how to
    fix). Optionally writes a full report (format by extension: .md/.html/.json)."""
    try:
        results = json.loads(results_json)
    except Exception as e:
        return f"Could not parse results_json: {e}"
    if isinstance(results, dict):
        results = results.get("results", [results])
    sc = _readiness.build_scorecard(results, meta={"title": title})
    if report_path:
        _write_report(results, report_path, title=title, scorecard=sc)
    if verbose:
        return fmt.dumps(sc)
    lines = [f"🧭 {sc['verdict']} — overall {sc['overall_score']}/100",
             f"   {sc['verdict_reason']}",
             f"   findings: {sc['severity_counts']['high']}H "
             f"{sc['severity_counts']['medium']}M {sc['severity_counts']['low']}L", "Category scores:"]
    for cat, d in sc["categories"].items():
        lines.append(f"  {cat}: {d['score']}/100 ({d['findings']} findings)")
    lines.append("Top fixes:")
    for i, rec in enumerate(sc["recommendations"][:6], 1):
        lines.append(f"  {i}. [{rec['severity']}] {rec['type']} ({rec['count']}×) — {rec['fix']}")
    if report_path:
        lines.insert(0, f"Report → {report_path}")
    return "\n".join(lines)


# ------------------------------------------------- self-healing / power tools
@mcp.tool()
@_browser_tool
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


# ---------------------------------------------------- authenticated sessions
@mcp.tool()
@_browser_tool
async def save_session(name: str = "default") -> str:
    """Save the CURRENT logged-in browser session (cookies + localStorage) to
    disk under `name`. Log in first (e.g. via run_journey), then save — later
    calls to load_session restore it so you can test behind auth."""
    return await _session.save_session(name)


@mcp.tool()
@_browser_tool
async def load_session(name: str = "default") -> str:
    """Restore a saved session into a fresh browser context so the browser is
    authenticated. Then crawl / deep_test / security_scan run AS that user —
    unlocking dashboards, account pages, checkout, and authorization testing."""
    return await _session.load_session(name)


@mcp.tool()
def list_sessions() -> str:
    """List saved authenticated sessions (name + cookie/localStorage counts)."""
    return _session.list_sessions()


@mcp.tool()
def delete_session(name: str) -> str:
    """Delete a saved session by name."""
    return _session.delete_session(name)


@mcp.tool()
@_browser_tool
async def connect_chrome(port: int = 9222) -> str:
    """Launch YOUR real Chrome with remote debugging on and attach to it — fully
    automatic, no manual chrome://inspect step. Uses a dedicated Fagun profile."""
    cdp = launch_debuggable_chrome(port)
    await manager.stop()
    msg = await manager.start()
    return f"Chrome launched with debugging at {cdp}. {msg}"


@mcp.tool()
async def write_report(results_json: str, path: str, title: str = "Fagun QA Report",
                       readiness: bool = True) -> str:
    """Write a report from a JSON list of results. Format follows the file
    extension: .md (Markdown) / .html (web page) / .json / .xml (JUnit for CI).
    With readiness=True, prepends a product-readiness scorecard + release verdict."""
    results = json.loads(results_json)
    if isinstance(results, dict):
        results = [results]
    sc = _readiness.build_scorecard(results) if readiness else None
    _write_report(results, path, title=title, scorecard=sc)
    verdict = f" — {sc['verdict']} ({sc['overall_score']}/100)" if sc else ""
    return f"Report written to {path}{verdict}"


def serve() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    serve()
