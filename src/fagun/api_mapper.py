"""API surface mapper — intercept all network traffic during page load and
interaction to produce a complete map of REST endpoints, GraphQL queries,
WebSocket connections, and third-party integrations.

Every request is captured via Playwright route interception so nothing is
blocked. Auth patterns are detected from headers. Security findings are
reported when unprotected data endpoints, insecure HTTP API calls, or
verbose error responses (with stack traces) are observed.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse

from .browser import manager

_STATIC_EXTS = re.compile(
    r"\.(js|mjs|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|map|webp|avif|mp4|mp3|pdf)(\?|$)",
    re.I,
)
_API_PATHS = re.compile(
    r"/(api|v\d+|graphql|query|rest|service|endpoint|rpc|ajax|xhr|fetch|data|backend)(/|$)",
    re.I,
)
_AUTH_HEADERS = ("authorization", "x-api-key", "x-auth-token", "x-access-token",
                 "token", "api-key", "x-token", "x-session-token")
_SAFE_CLICK_ROLES = ("tab", "button", "menuitem", "option", "treeitem", "link")
_SKIP_LABELS = re.compile(
    r"\b(delete|remove|cancel|logout|sign.?out|pay|submit|confirm|close|dismiss|deny)\b",
    re.I,
)


def _categorise(req_url: str, method: str, origin: str, body: str = "") -> str:
    p = urlparse(req_url)
    ext = _STATIC_EXTS.search(req_url)
    if ext:
        return "static"
    if p.scheme in ("ws", "wss"):
        return "websocket"
    path = p.path + ("?" + p.query if p.query else "")
    if p.netloc != urlparse(origin).netloc:
        return "third_party"
    if method.upper() == "POST" and ("graphql" in req_url.lower() or
                                      "query {" in body or '"query"' in body):
        return "graphql"
    if _API_PATHS.search(req_url):
        return "rest_api"
    return "other"


def _detect_auth(headers: dict[str, str]) -> str:
    auth = headers.get("authorization", "").lower()
    if "bearer" in auth:
        return "bearer"
    if "basic" in auth:
        return "basic"
    for h in _AUTH_HEADERS:
        if headers.get(h):
            return "apikey"
    if headers.get("cookie"):
        return "cookie"
    return "none"


def _mask_auth(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        if k.lower() in _AUTH_HEADERS or k.lower() == "cookie":
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


async def map_api(url: str, interact: bool = True, timeout: int = 20000) -> dict[str, Any]:
    """Navigate to url, intercept all network traffic, optionally interact with
    the page to trigger lazy API calls. Return a structured API surface map."""
    page = await manager.page()
    origin = urlparse(url).scheme + "://" + urlparse(url).netloc

    endpoints: list[dict[str, Any]] = []
    graphql_ops: list[dict[str, Any]] = []
    websockets: list[str] = []
    third_party: list[dict[str, Any]] = []
    _seen_paths: set[str] = set()
    findings: list[dict[str, Any]] = []
    auth_patterns: set[str] = set()

    # Track timing per request
    _timings: dict[str, float] = {}

    async def on_request(request) -> None:
        _timings[request.url] = time.perf_counter()
        # Capture websocket upgrades
        if request.url.startswith(("ws://", "wss://")):
            websockets.append(request.url)

    async def on_response(response) -> None:
        req = response.request
        req_url = req.url
        method = req.method
        status = response.status
        t0 = _timings.pop(req_url, time.perf_counter())
        ms = round((time.perf_counter() - t0) * 1000)

        # Get headers safely
        try:
            req_headers = {k.lower(): v for k, v in req.headers.items()}
        except Exception:
            req_headers = {}

        # Try to get response body for error disclosure check
        body_snippet = ""
        if status >= 400:
            try:
                body_snippet = (await response.text())[:500]
            except Exception:
                pass

        # Request body (for GraphQL detection)
        req_body = ""
        try:
            post_data = req.post_data
            if post_data:
                req_body = post_data[:200]
        except Exception:
            pass

        category = _categorise(req_url, method, origin, req_body)
        auth = _detect_auth(req_headers)
        if auth != "none":
            auth_patterns.add(auth)

        p = urlparse(req_url)
        path_key = f"{method.upper()} {p.path}"

        if category == "rest_api":
            if path_key not in _seen_paths:
                _seen_paths.add(path_key)
                entry = {
                    "method": method.upper(),
                    "path": p.path,
                    "url": req_url,
                    "status": status,
                    "auth": auth,
                    "ms": ms,
                    "headers": _mask_auth(req_headers),
                }
                endpoints.append(entry)

                # Security: API over HTTP
                if p.scheme == "http":
                    findings.append({
                        "severity": "high",
                        "type": "api-insecure",
                        "detail": f"API call over HTTP (not HTTPS): {method.upper()} {req_url}",
                    })

                # Security: data endpoint with no auth
                if auth == "none" and status < 400 and method.upper() in ("GET", "POST"):
                    if any(kw in p.path.lower() for kw in
                           ("/user", "/account", "/profile", "/admin", "/data", "/report",
                            "/analytics", "/billing", "/payment", "/order", "/customer")):
                        findings.append({
                            "severity": "medium",
                            "type": "api-no-auth",
                            "detail": f"Potentially sensitive endpoint with no auth header: {method.upper()} {p.path}",
                        })

        elif category == "graphql":
            if path_key not in _seen_paths:
                _seen_paths.add(path_key)
                op_name = ""
                try:
                    body_json = __import__("json").loads(req_body)
                    op_name = body_json.get("operationName") or body_json.get("query", "")[:60]
                except Exception:
                    op_name = req_body[:60]
                graphql_ops.append({
                    "method": method.upper(),
                    "url": req_url,
                    "operation": op_name,
                    "status": status,
                    "auth": auth,
                    "ms": ms,
                })

        elif category == "third_party":
            tp_domain = urlparse(req_url).netloc
            if not any(t["domain"] == tp_domain for t in third_party):
                third_party.append({
                    "domain": tp_domain,
                    "example_url": req_url,
                    "method": method.upper(),
                })

        # Security: verbose error disclosure (stack trace in 4xx/5xx)
        if status >= 400 and body_snippet:
            if any(kw in body_snippet for kw in
                   ("Traceback", "stack trace", "Error:", "Exception", "at line ",
                    "undefined is not", "Cannot read prop", "SyntaxError")):
                findings.append({
                    "severity": "medium",
                    "type": "api-error-disclosure",
                    "detail": f"{method.upper()} {p.path} → {status} with verbose error",
                    "evidence": body_snippet[:200],
                })

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="networkidle", timeout=timeout)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except Exception:
            pass

    if interact:
        # Scroll to trigger lazy-loaded content
        try:
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(0.5)
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # Click safe interactive elements to trigger API calls
        safe_selectors = [
            '[role="tab"]',
            'button:not([type="submit"]):not([type="reset"])',
            '[data-toggle]',
            '[aria-expanded="false"]',
            'summary',
        ]
        clicked = 0
        for sel in safe_selectors:
            if clicked >= 10:
                break
            try:
                els = await page.query_selector_all(sel)
                for el in els[:3]:
                    try:
                        label = (await el.text_content() or "").strip()
                        if _SKIP_LABELS.search(label):
                            continue
                        if not await el.is_visible():
                            continue
                        await el.click(timeout=2000)
                        await asyncio.sleep(0.4)
                        clicked += 1
                        # Close any modal that opened
                        try:
                            await page.keyboard.press("Escape")
                        except Exception:
                            pass
                    except Exception:
                        continue
            except Exception:
                continue

        await asyncio.sleep(1)

    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)

    # Determine overall auth pattern
    if "bearer" in auth_patterns:
        auth_pattern = "bearer"
    elif "apikey" in auth_patterns:
        auth_pattern = "apikey"
    elif "cookie" in auth_patterns:
        auth_pattern = "cookie"
    elif "basic" in auth_patterns:
        auth_pattern = "basic"
    else:
        auth_pattern = "none"

    # Security: no auth on any API endpoint
    if auth_pattern == "none" and endpoints:
        findings.append({
            "severity": "medium",
            "type": "api-no-global-auth",
            "detail": f"None of the {len(endpoints)} API endpoints observed use an auth header",
        })

    return {
        "url": url,
        "endpoints": endpoints,
        "graphql": graphql_ops,
        "websockets": websockets,
        "third_party": third_party,
        "auth_pattern": auth_pattern,
        "summary": {
            "rest_endpoints": len(endpoints),
            "graphql_operations": len(graphql_ops),
            "websocket_connections": len(websockets),
            "third_party_domains": len(third_party),
        },
        "findings": findings,
    }
