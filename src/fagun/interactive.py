"""Interactive SPA explorer — discover hidden pages and UI states by clicking
through all safe interactive elements on a page.

Standard crawlers follow <a href> links but miss:
- Tab panels that only render their content after a click
- Accordion sections, drawers, side panels
- Dropdown menus that reveal sub-navigation
- Modal dialogs with forms or content
- Dynamic routes loaded via JS router on button click

This module clicks through those elements, records what appears (new URL,
new DOM content, console errors), and returns discovered URLs + UI states
that should be added to the test surface.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from .browser import manager

_SKIP_LABELS = re.compile(
    r"\b(delete|remove|cancel|log.?out|sign.?out|pay|purchase|buy|submit|confirm|"
    r"close|dismiss|deny|decline|reject|deactivate|disable|revoke|unlink|disconnect)\b",
    re.I,
)

_DISCLOSURE_ROLES = {
    "tab", "button", "menuitem", "menuitemcheckbox", "menuitemradio",
    "treeitem", "option", "switch", "radio",
}

# Elements likely to open modals or expand sections
_DISCLOSURE_SELECTORS = [
    '[role="tab"]',
    '[aria-expanded]',
    '[data-toggle]',
    '[data-bs-toggle]',
    'summary',  # <details><summary>
    '[aria-haspopup="dialog"]',
    '[aria-haspopup="menu"]',
    'button[aria-controls]',
    '[data-modal-target]',
    '[data-drawer-target]',
    '[data-accordion-target]',
]

# Nav/sidebar links that could lead to new pages
_NAV_SELECTORS = [
    'nav a[href]',
    '[role="navigation"] a[href]',
    'aside a[href]',
    '.sidebar a[href]',
    '.menu a[href]',
    '.drawer a[href]',
    '[aria-label*="nav" i] a[href]',
]


def _same_origin(url_a: str, url_b: str) -> bool:
    a, b = urlparse(url_a), urlparse(url_b)
    return a.scheme == b.scheme and a.netloc == b.netloc


def _label_el(info: dict) -> str:
    """Build a human-readable label from element info."""
    parts = []
    if info.get("role"):
        parts.append(f'[{info["role"]}]')
    text = (info.get("text") or "").strip()[:50]
    if text:
        parts.append(f'"{text}"')
    aria = (info.get("ariaLabel") or "").strip()[:40]
    if aria and aria != text:
        parts.append(f'aria="{aria}"')
    tag = info.get("tag", "")
    if tag:
        parts.append(tag)
    return " ".join(parts) or "unknown"


async def explore_interactions(url: str, max_clicks: int = 30) -> dict[str, Any]:
    """Click through interactive elements, discover hidden pages and UI states."""
    page = await manager.page()
    original_url = url

    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            return {"url": url, "error": str(e), "clicks_attempted": 0,
                    "new_urls_discovered": [], "interactive_states": [], "findings": []}

    # Capture initial DOM fingerprint (rough)
    initial_dom_len = await page.evaluate("() => document.body.innerHTML.length")

    new_urls: list[str] = []
    states: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    clicks_attempted = 0

    # Collect all candidate elements
    candidate_infos: list[dict[str, Any]] = await page.evaluate(
        """() => {
            const selectors = [
                '[role="tab"]', '[aria-expanded]', '[data-toggle]',
                '[data-bs-toggle]', 'summary', '[aria-haspopup]',
                'button[aria-controls]', '[data-modal-target]',
                '[data-accordion-target]', 'nav a[href]',
                '[role="navigation"] a[href]', 'aside a[href]',
                '.sidebar a[href]', '[role="menuitem"]',
            ];
            const seen = new Set();
            const results = [];
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (seen.has(el)) continue;
                    seen.add(el);
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    results.push({
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || '',
                        text: (el.textContent || '').trim().slice(0, 60),
                        ariaLabel: el.getAttribute('aria-label') || '',
                        href: el.getAttribute('href') || '',
                        expanded: el.getAttribute('aria-expanded'),
                        selector: (() => {
                            if (el.id) return '#' + CSS.escape(el.id);
                            const idx = [...el.parentElement.children].indexOf(el);
                            return el.tagName.toLowerCase() + ':nth-child(' + (idx+1) + ')';
                        })(),
                    });
                }
            }
            return results.slice(0, 60);
        }"""
    )

    for info in candidate_infos:
        if clicks_attempted >= max_clicks:
            break

        label = _label_el(info)

        # Skip destructive/risky labels
        if _SKIP_LABELS.search(label):
            continue

        # If it's a link going to a different page on same origin, record URL
        href = info.get("href", "")
        if href and href.startswith("/"):
            abs_href = urlparse(url).scheme + "://" + urlparse(url).netloc + href
            if abs_href not in new_urls and abs_href != url:
                new_urls.append(abs_href)
            continue
        if href and href.startswith("http"):
            if _same_origin(url, href) and href not in new_urls and href != url:
                new_urls.append(href)
            continue

        # Click the element
        selector = info.get("selector", "")
        if not selector:
            continue

        manager.clear_logs()
        prev_url = page.url
        prev_dom_len = await page.evaluate("() => document.body.innerHTML.length")

        try:
            await page.click(selector, timeout=3000)
            await asyncio.sleep(0.5)
            clicks_attempted += 1
        except Exception:
            clicks_attempted += 1
            continue

        after_url = page.url
        after_dom_len = await page.evaluate("() => document.body.innerHTML.length")

        console_errors = sum(1 for c in manager.console if c.type == "error")
        dom_changed = abs(after_dom_len - prev_dom_len) > 100

        # Navigated to a new URL
        if after_url != prev_url:
            if _same_origin(url, after_url) and after_url not in new_urls:
                new_urls.append(after_url)
            # Go back
            try:
                await page.go_back(timeout=5000)
                await asyncio.sleep(0.3)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    pass
            states.append({
                "trigger": label,
                "reveals": f"navigation → {after_url}",
                "errors": console_errors,
            })
        elif dom_changed:
            # Something appeared — check for modal, drawer, panel
            new_content = await page.evaluate(
                """() => {
                    const modal = document.querySelector('[role="dialog"],[role="alertdialog"],.modal,.drawer,.panel,.sidebar.open,.sheet');
                    if (modal) return modal.textContent.trim().slice(0, 80);
                    // Find new visible content
                    const added = document.querySelector('[aria-expanded="true"]');
                    if (added) return added.textContent.trim().slice(0, 80);
                    return 'DOM changed (+' + Math.abs(document.body.innerHTML.length) + ' chars)';
                }"""
            )
            states.append({
                "trigger": label,
                "reveals": new_content or "UI state changed",
                "errors": console_errors,
            })
            # Dismiss any open modal/dialog
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
            except Exception:
                pass

        # Record console errors triggered by this click
        if console_errors:
            for c in list(manager.console):
                if c.type == "error":
                    findings.append({
                        "severity": "medium",
                        "type": "interaction-error",
                        "detail": f"JS error after clicking {label!r}: {c.text[:200]}",
                    })
            findings = findings[:20]  # cap

    # Also discover nav links not yet in new_urls
    try:
        hrefs = await page.evaluate(
            """() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href))]"""
        )
        for h in hrefs:
            if _same_origin(url, h) and h not in new_urls and h.rstrip("/") != url.rstrip("/"):
                path = urlparse(h).path
                # Only add page-like paths (skip anchors, static files)
                if not re.search(r"\.(js|css|png|jpg|gif|svg|ico|woff|pdf)$", path, re.I):
                    new_urls.append(h)
    except Exception:
        pass

    return {
        "url": original_url,
        "clicks_attempted": clicks_attempted,
        "new_urls_discovered": new_urls[:100],
        "interactive_states": states,
        "findings": findings,
        "summary": {
            "new_pages": len(new_urls),
            "ui_states_revealed": len(states),
            "interaction_errors": sum(1 for f in findings if f["type"] == "interaction-error"),
        },
    }
