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
    try:
        resp = await page.goto(url, wait_until="load", timeout=30000)
    except Exception as e:
        return {
            "url": url,
            "ok": False,
            "findings": [{"severity": "high", "type": "load-failure", "detail": str(e)}],
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

    return {
        "url": url,
        "ok": True,
        "status": status,
        "load_ms": load_ms,
        "console_count": len(manager.console),
        "network_count": len(manager.network),
        "findings": findings,
    }
