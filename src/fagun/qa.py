"""QA engine — crawl a site and run an automated bug/quality sweep.

Findings are plain dicts so they serialize cleanly back to the AI tool and into
the report writer.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from .browser import manager


def _same_site(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


async def crawl(start_url: str, max_pages: int = 20) -> dict[str, Any]:
    """Breadth-first crawl within the same host. Returns discovered pages."""
    page = await manager.page()
    seen: set[str] = set()
    queue: list[str] = [urldefrag(start_url)[0]]
    pages: list[dict[str, Any]] = []

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status = resp.status if resp else None
            title = await page.title()
        except Exception as e:
            pages.append({"url": url, "status": None, "error": str(e)})
            continue

        hrefs = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
        links = []
        for h in hrefs:
            if not h or h.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urldefrag(urljoin(url, h))[0]
            links.append(absolute)
            if _same_site(start_url, absolute) and absolute not in seen:
                queue.append(absolute)

        pages.append(
            {"url": url, "status": status, "title": title, "links_found": len(links)}
        )

    return {"start": start_url, "crawled": len(pages), "pages": pages}


async def run_qa(url: str) -> dict[str, Any]:
    """Load one page and collect findings across several quality dimensions."""
    page = await manager.page()
    manager.clear_logs()
    findings: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    resp = None
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = await page.goto(url, wait_until="load", timeout=30000)
            last_err = None
            break
        except Exception as e:
            last_err = e  # e.g. "interrupted by another navigation" — settle and retry
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
    if last_err is not None:
        return {
            "url": url,
            "ok": False,
            "findings": [{"severity": "high", "type": "load-failure", "detail": str(last_err)}],
        }
    load_ms = round((time.perf_counter() - t0) * 1000)

    status = resp.status if resp else None
    if status and status >= 400:
        findings.append(
            {"severity": "high", "type": "http-error", "detail": f"Page returned {status}"}
        )

    # Console errors / warnings.
    for c in manager.console:
        if c.type in ("error", "warning"):
            findings.append(
                {
                    "severity": "high" if c.type == "error" else "low",
                    "type": f"console-{c.type}",
                    "detail": c.text[:300],
                    "at": c.location,
                }
            )

    # Failed / erroring network requests.
    for n in manager.network:
        if n.failure:
            findings.append(
                {"severity": "high", "type": "request-failed", "detail": f"{n.method} {n.url} — {n.failure}"}
            )
        elif n.status and n.status >= 400:
            findings.append(
                {"severity": "medium", "type": "bad-response", "detail": f"{n.status} {n.method} {n.url}"}
            )

    # Basic accessibility heuristics.
    imgs_no_alt = await page.eval_on_selector_all(
        "img:not([alt])", "els => els.length"
    )
    if imgs_no_alt:
        findings.append(
            {"severity": "low", "type": "a11y-img-alt", "detail": f"{imgs_no_alt} <img> without alt"}
        )
    inputs_no_label = await page.evaluate(
        """() => {
            const inputs = [...document.querySelectorAll('input,select,textarea')];
            return inputs.filter(el => {
                if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return false;
                if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
                if (el.id && document.querySelector(`label[for="${el.id}"]`)) return false;
                return !el.closest('label');
            }).length;
        }"""
    )
    if inputs_no_label:
        findings.append(
            {"severity": "low", "type": "a11y-input-label", "detail": f"{inputs_no_label} form fields without a label"}
        )
    if not await page.query_selector("title, h1"):
        findings.append({"severity": "low", "type": "seo", "detail": "No <title> or <h1>"})

    # Performance signal.
    if load_ms > 4000:
        findings.append(
            {"severity": "medium", "type": "perf", "detail": f"Load took {load_ms} ms (>4s)"}
        )

    # Dedup identical findings (a retried load can double-fire console/network).
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for f in findings:
        key = (f.get("type", ""), f.get("detail", ""))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return {
        "url": url,
        "ok": True,
        "status": status,
        "load_ms": load_ms,
        "console_count": len(manager.console),
        "network_count": len(manager.network),
        "findings": unique,
    }


# --- security headers ------------------------------------------------------
_SEC_HEADERS = {
    "content-security-policy": ("high", "Missing CSP — XSS/injection risk"),
    "strict-transport-security": ("medium", "Missing HSTS — downgrade/MITM risk"),
    "x-frame-options": ("medium", "Missing X-Frame-Options — clickjacking risk"),
    "x-content-type-options": ("low", "Missing X-Content-Type-Options: nosniff"),
    "referrer-policy": ("low", "Missing Referrer-Policy"),
    "permissions-policy": ("low", "Missing Permissions-Policy"),
}


async def security_headers(url: str) -> dict[str, Any]:
    """Fetch a URL and check for missing/weak security response headers."""
    page = await manager.page()
    findings: list[dict[str, Any]] = []
    if not url.lower().startswith("http"):
        return {"url": url, "skipped": "security headers only apply to http(s)", "findings": []}
    resp = await page.request.get(url, timeout=20000)
    headers = {k.lower(): v for k, v in resp.headers.items()}

    for h, (sev, msg) in _SEC_HEADERS.items():
        if h not in headers:
            findings.append({"severity": sev, "type": "sec-header", "detail": msg})

    server = headers.get("server", "")
    if server and any(c.isdigit() for c in server):
        findings.append(
            {"severity": "low", "type": "info-leak", "detail": f"Server header leaks version: {server}"}
        )
    if "x-powered-by" in headers:
        findings.append(
            {"severity": "low", "type": "info-leak", "detail": f"X-Powered-By leaks stack: {headers['x-powered-by']}"}
        )
    return {"url": url, "status": resp.status, "headers_present": sorted(headers), "findings": findings}


# --- broken link checker ---------------------------------------------------
async def check_links(url: str, max_links: int = 100) -> dict[str, Any]:
    """Collect links on a page and probe each; report broken ones (4xx/5xx/fail)."""
    page = await manager.page()
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    hrefs = await page.eval_on_selector_all(
        "a[href]", "els => [...new Set(els.map(e => e.href))]"
    )
    hrefs = [h for h in hrefs if h.startswith("http")][:max_links]
    findings: list[dict[str, Any]] = []
    checked = 0
    for h in hrefs:
        try:
            r = await page.request.head(h, timeout=15000)
            st = r.status
            if st == 405:  # HEAD not allowed -> retry GET
                r = await page.request.get(h, timeout=15000)
                st = r.status
            checked += 1
            if st >= 400:
                findings.append(
                    {"severity": "medium", "type": "broken-link", "detail": f"{st} → {h}"}
                )
        except Exception as e:
            findings.append({"severity": "medium", "type": "broken-link", "detail": f"unreachable → {h} ({e})"})
    return {"url": url, "links_checked": checked, "findings": findings}


# --- form auditor ----------------------------------------------------------
async def test_forms(url: str) -> dict[str, Any]:
    """Static + DOM audit of every form on a page. Non-destructive (no submit)."""
    page = await manager.page()
    await page.goto(url, wait_until="load", timeout=20000)
    forms = await page.evaluate(
        """() => [...document.forms].map(f => ({
            action: f.getAttribute('action') || location.href,
            method: (f.getAttribute('method') || 'get').toLowerCase(),
            fields: [...f.elements].filter(e => e.name || e.id).map(e => ({
                name: e.name || e.id, type: e.type,
                required: e.required, hasLabel: !!(e.labels && e.labels.length) ||
                    !!e.getAttribute('aria-label'),
                autocomplete: e.getAttribute('autocomplete') || ''
            }))
        }))"""
    )
    findings: list[dict[str, Any]] = []
    for i, f in enumerate(forms):
        tag = f"form#{i} ({f['method'].upper()} {f['action']})"
        if f["method"] == "get" and any(
            fld["type"] == "password" for fld in f["fields"]
        ):
            findings.append({"severity": "high", "type": "form-security", "detail": f"{tag} submits a password over GET"})
        if str(f["action"]).startswith("http://"):
            findings.append({"severity": "high", "type": "form-security", "detail": f"{tag} posts to insecure http://"})
        for fld in f["fields"]:
            if not fld["hasLabel"] and fld["type"] not in ("hidden", "submit", "button"):
                findings.append({"severity": "low", "type": "form-a11y", "detail": f"{tag} field {fld['name']!r} has no label"})
            if fld["type"] == "password" and fld["autocomplete"] not in ("new-password", "current-password"):
                findings.append({"severity": "low", "type": "form-hint", "detail": f"{tag} password field missing autocomplete hint"})
            if not fld["required"] and fld["type"] in ("email", "password", "tel"):
                findings.append({"severity": "low", "type": "form-validation", "detail": f"{tag} {fld['type']} field {fld['name']!r} not marked required"})
    return {"url": url, "forms": len(forms), "findings": findings}


async def deep_test(url: str, max_pages: int = 8) -> dict[str, Any]:
    """Everything: crawl → per-page QA + forms + security headers, aggregated."""
    crawl_result = await crawl(url, max_pages)
    results: list[dict[str, Any]] = []
    for p in crawl_result["pages"]:
        if p.get("error") or (p.get("status") and p["status"] >= 400):
            continue
        page_url = p["url"]
        merged = await run_qa(page_url)
        for check in (test_forms, security_headers):
            try:
                merged["findings"].extend((await check(page_url)).get("findings", []))
            except Exception as e:
                merged["findings"].append(
                    {"severity": "low", "type": "check-error", "detail": f"{check.__name__} failed: {e}"}
                )
        results.append(merged)
    return {"start": url, "pages_tested": len(results), "results": results}
