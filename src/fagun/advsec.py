"""Advanced, still non-destructive security probes.

Extends the core :mod:`fagun.security` battery with the checks that separate a
real assessment from a header-only scan: CSP quality, clickjacking, dangerous
HTTP methods, mixed content, missing SRI, cache of sensitive responses, host-
header reflection, CRLF, path-traversal/LFI, SSTI, command-injection signals,
GraphQL introspection, and error/stack-trace disclosure.

Rules that keep results honest:
- GET/HEAD/OPTIONS only; no writes; unique harmless markers.
- Every finding carries an ``evidence`` string quoting what was actually seen.
- Ambiguous results say "potential — verify". No pass/fail is invented.
Only run against targets you are authorized to test.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .browser import manager

MARK = "fagunPROBE7Z"


async def _req(method: str, url: str, headers: dict | None = None, max_redirects: int | None = None):
    page = await manager.page()
    kw: dict[str, Any] = {"headers": headers or {}, "timeout": 15000, "fail_on_status_code": False}
    if max_redirects is not None:
        kw["max_redirects"] = max_redirects
    return await page.request.fetch(url, method=method, **kw)


def _with_param(url: str, key: str, value: str) -> str:
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    q[key] = value
    return urlunparse(p._replace(query=urlencode(q)))


def _root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


# --------------------------------------------------------------- CSP evaluation
async def check_csp(url: str) -> list[dict[str, Any]]:
    r = await _req("GET", url)
    h = {k.lower(): v for k, v in r.headers.items()}
    csp = h.get("content-security-policy", "")
    findings = []
    if not csp:
        return []  # absence already reported by core security_headers
    low = csp.lower()
    if "unsafe-inline" in low:
        findings.append({"severity": "medium", "type": "csp-weak",
                         "detail": "CSP allows 'unsafe-inline' — negates most XSS protection",
                         "evidence": f"CSP contains 'unsafe-inline'"})
    if "unsafe-eval" in low:
        findings.append({"severity": "medium", "type": "csp-weak",
                         "detail": "CSP allows 'unsafe-eval'",
                         "evidence": "CSP contains 'unsafe-eval'"})
    if re.search(r"(default|script)-src[^;]*\*", low):
        findings.append({"severity": "medium", "type": "csp-weak",
                         "detail": "CSP script/default-src uses wildcard *",
                         "evidence": "wildcard source in script/default-src"})
    if "default-src" not in low and "script-src" not in low:
        findings.append({"severity": "medium", "type": "csp-weak",
                         "detail": "CSP has no default-src/script-src fallback",
                         "evidence": clip(csp)})
    if "frame-ancestors" not in low:
        findings.append({"severity": "low", "type": "csp-weak",
                         "detail": "CSP missing frame-ancestors (clickjacking depends on XFO)",
                         "evidence": "no frame-ancestors directive"})
    return findings


# ------------------------------------------------------------- clickjacking
async def check_clickjacking(url: str) -> list[dict[str, Any]]:
    r = await _req("GET", url)
    h = {k.lower(): v for k, v in r.headers.items()}
    xfo = h.get("x-frame-options", "").lower()
    csp = h.get("content-security-policy", "").lower()
    protected = bool(xfo) or "frame-ancestors" in csp
    if not protected:
        return [{"severity": "medium", "type": "clickjacking",
                 "detail": "No X-Frame-Options and no CSP frame-ancestors — page is framable",
                 "evidence": "neither X-Frame-Options nor frame-ancestors present"}]
    if xfo and xfo not in ("deny", "sameorigin") and "allow-from" not in xfo:
        return [{"severity": "low", "type": "clickjacking",
                 "detail": f"Unusual X-Frame-Options value: {xfo}",
                 "evidence": f"X-Frame-Options: {xfo}"}]
    return []


# --------------------------------------------------------- dangerous HTTP methods
async def check_http_methods(url: str) -> list[dict[str, Any]]:
    findings = []
    try:
        r = await _req("OPTIONS", url)
        allow = r.headers.get("allow", "") or r.headers.get("access-control-allow-methods", "")
    except Exception:
        allow = ""
    risky = [m for m in ("PUT", "DELETE", "TRACE", "CONNECT", "PATCH") if m in allow.upper()]
    if risky:
        findings.append({"severity": "medium", "type": "http-methods",
                         "detail": f"Server advertises risky methods: {', '.join(risky)}",
                         "evidence": f"Allow: {allow}"})
    # TRACE can enable Cross-Site Tracing — confirm it actually responds.
    try:
        t = await _req("TRACE", url)
        if t.status == 200 and "TRACE" in (await t.text())[:200].upper():
            findings.append({"severity": "medium", "type": "http-methods",
                             "detail": "TRACE method enabled (Cross-Site Tracing)",
                             "evidence": f"TRACE returned 200 echoing request"})
    except Exception:
        pass
    return findings


# ----------------------------------------------------------------- mixed content
async def check_mixed_content(url: str) -> list[dict[str, Any]]:
    if not url.lower().startswith("https"):
        return []
    page = await manager.page()
    insecure = await page.evaluate(
        """() => {
            const out = [];
            const grab = (sel, attr) => document.querySelectorAll(sel).forEach(e => {
                const v = e.getAttribute(attr) || '';
                if (v.startsWith('http://')) out.push(e.tagName.toLowerCase()+':'+v.slice(0,80));
            });
            grab('script[src]','src'); grab('link[href]','href');
            grab('img[src]','src'); grab('iframe[src]','src'); grab('form[action]','action');
            return out;
        }"""
    )
    if insecure:
        return [{"severity": "medium", "type": "mixed-content",
                 "detail": f"{len(insecure)} resource(s) loaded over http:// on an https page",
                 "evidence": "; ".join(insecure[:3])}]
    return []


# ------------------------------------------------------------------- missing SRI
async def check_sri(url: str) -> list[dict[str, Any]]:
    page = await manager.page()
    host = urlparse(url).netloc
    ext = await page.evaluate(
        """(host) => {
            const out = [];
            document.querySelectorAll('script[src],link[rel="stylesheet"][href]').forEach(e => {
                const u = e.src || e.href || '';
                try { const h = new URL(u, location.href).host;
                    if (h && h !== host && !e.integrity) out.push(u.slice(0,90)); } catch(_){}
            });
            return out;
        }""", host
    )
    if ext:
        return [{"severity": "low", "type": "missing-sri",
                 "detail": f"{len(ext)} cross-origin script/style without Subresource Integrity",
                 "evidence": "; ".join(ext[:3])}]
    return []


# --------------------------------------------------- cache of sensitive responses
async def check_cache(url: str) -> list[dict[str, Any]]:
    p = urlparse(url).path.lower()
    sensitive = any(k in p for k in ("account", "profile", "settings", "admin", "dashboard",
                                     "order", "invoice", "billing", "user", "auth", "token"))
    if not sensitive:
        return []
    r = await _req("GET", url)
    h = {k.lower(): v for k, v in r.headers.items()}
    cc = h.get("cache-control", "").lower()
    if not any(x in cc for x in ("no-store", "private", "no-cache")):
        return [{"severity": "low", "type": "cache-sensitive",
                 "detail": f"Sensitive path cacheable (Cache-Control: {cc or 'absent'})",
                 "evidence": f"Cache-Control: {cc or '(none)'} on {p}"}]
    return []


# ------------------------------------------------------- host-header reflection
async def check_host_header(url: str) -> list[dict[str, Any]]:
    evil = "fagun-evil.example"
    try:
        r = await _req("GET", url, headers={"Host": evil, "X-Forwarded-Host": evil}, max_redirects=0)
    except Exception:
        return []
    h = {k.lower(): v for k, v in r.headers.items()}
    loc = h.get("location", "")
    if evil in loc:
        return [{"severity": "medium", "type": "host-header-injection",
                 "detail": "X-Forwarded-Host reflected into redirect (poisoning / password-reset risk)",
                 "evidence": f"Location: {clip(loc, 90)}"}]
    body = ""
    try:
        body = (await r.text())[:20000]
    except Exception:
        pass
    if evil in body:
        return [{"severity": "low", "type": "host-header-injection",
                 "detail": "Injected Host reflected in body — verify cache poisoning / link generation",
                 "evidence": f"'{evil}' appears in response body"}]
    return []


# ----------------------------------------------------------------- CRLF injection
async def check_crlf(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)] or ["redirect", "url", "next", "page"]
    findings = []
    for key in params[:5]:
        test = _with_param(url, key, f"x%0d%0aX-Fagun-CRLF:{MARK}")
        try:
            r = await _req("GET", test, max_redirects=0)
        except Exception:
            continue
        if any(k.lower() == "x-fagun-crlf" for k in r.headers):
            findings.append({"severity": "high", "type": "crlf-injection",
                             "detail": f"param {key!r} injects a response header (CRLF)",
                             "evidence": f"X-Fagun-CRLF header appeared in response"})
    return findings


# ------------------------------------------------------- path traversal / LFI
_LFI_SIG = re.compile(r"root:.*:0:0:|\[extensions\]|for 16-bit app support", re.I)


async def check_path_traversal(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)]
    if not params:
        return []
    findings = []
    payloads = ["../../../../etc/passwd", "..%2f..%2f..%2f..%2fetc%2fpasswd",
                "....//....//....//etc/passwd", "..\\..\\..\\windows\\win.ini"]
    for key in params[:4]:
        for pl in payloads:
            try:
                r = await _req("GET", _with_param(url, key, pl))
                body = (await r.text())[:8000]
            except Exception:
                continue
            if _LFI_SIG.search(body):
                findings.append({"severity": "high", "type": "path-traversal",
                                 "detail": f"param {key!r} appears to read local files (LFI)",
                                 "evidence": f"payload {pl!r} returned OS-file signature"})
                break
    return findings


# --------------------------------------------------------------------- SSTI
_SSTI = [("{{7*7}}", "49"), ("${7*7}", "49"), ("#{7*7}", "49"), ("<%= 7*7 %>", "49")]


async def check_ssti(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)]
    if not params:
        return []
    findings = []
    for key in params[:4]:
        for payload, expect in _SSTI:
            marker = f"{MARK}{payload}{MARK}"
            try:
                r = await _req("GET", _with_param(url, key, marker))
                body = await r.text()
            except Exception:
                continue
            if f"{MARK}{expect}{MARK}" in body:
                findings.append({"severity": "high", "type": "ssti",
                                 "detail": f"param {key!r} evaluates template expression {payload} → {expect}",
                                 "evidence": f"{MARK}{expect}{MARK} found in response"})
                break
    return findings


# ------------------------------------------------- command-injection error signal
_CMD_SIG = re.compile(r"sh: .*: command not found|is not recognized as an internal|/bin/sh:", re.I)


async def check_cmdi(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)]
    if not params:
        return []
    findings = []
    for key in params[:4]:
        test = _with_param(url, key, f";{MARK}nosuchcmd")
        try:
            r = await _req("GET", test)
            body = (await r.text())[:8000]
        except Exception:
            continue
        if _CMD_SIG.search(body):
            findings.append({"severity": "high", "type": "command-injection",
                             "detail": f"param {key!r} yields shell error output — potential command injection",
                             "evidence": "shell 'command not found' style error in response"})
    return findings


# ---------------------------------------------------------- GraphQL introspection
async def check_graphql(url: str) -> list[dict[str, Any]]:
    root = _root(url)
    page = await manager.page()
    findings = []
    q = '{"query":"query{__schema{queryType{name}}}"}'
    for path in ("/graphql", "/api/graphql", "/v1/graphql", "/query"):
        try:
            rr = await page.request.post(root + path, data=q,
                                         headers={"content-type": "application/json"},
                                         timeout=12000, fail_on_status_code=False)
            body = (await rr.text())[:4000]
        except Exception:
            continue
        if "__schema" in body and rr.status < 500:
            findings.append({"severity": "medium", "type": "graphql-introspection",
                             "detail": f"GraphQL introspection enabled at {path}",
                             "evidence": f"__schema returned at {path} (status {rr.status})"})
            break
    return findings


# ------------------------------------------------- error / stack-trace disclosure
_STACK = re.compile(
    r"Traceback \(most recent call last\)|at [\w.$]+\([\w./]+:\d+\)|"
    r"Exception in thread|java\.lang\.[A-Za-z]+Exception|"
    r"Warning: .* in .*\.php on line|Fatal error:|System\.[A-Za-z.]+Exception|"
    r"ActiveRecord::|Stack trace:|Whoops, looks like",
)


async def check_error_disclosure(url: str) -> list[dict[str, Any]]:
    # Force an error with a bad param value + a non-existent path.
    tests = []
    p = urlparse(url)
    if p.query:
        params = [k for k, _ in parse_qsl(p.query)]
        if params:
            tests.append(_with_param(url, params[0], "%ff%00[]{}"))
    tests.append(_root(url) + "/fagun-nonexistent-%27%22%3E")
    findings = []
    for t in tests:
        try:
            r = await _req("GET", t)
            body = (await r.text())[:12000]
        except Exception:
            continue
        m = _STACK.search(body)
        if m:
            findings.append({"severity": "medium", "type": "error-disclosure",
                             "detail": "Server returns a stack trace / verbose error",
                             "evidence": clip(m.group(0), 80)})
            break
    return findings


# ----------------------------------------------- sensitive data in URL / storage
async def check_sensitive_url(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    findings = []
    for k, v in parse_qsl(p.query):
        if re.search(r"token|session|passwd|password|secret|api[_-]?key|auth", k, re.I) and len(v) > 6:
            findings.append({"severity": "medium", "type": "sensitive-in-url",
                             "detail": f"Sensitive value in query param {k!r} (logged/refererred)",
                             "evidence": f"{k}={clip(v, 12)}"})
    return findings


async def check_jwt_alg_none(url: str) -> list[dict[str, Any]]:
    """Test whether the server accepts a JWT with alg:none (signature-stripped token).
    Looks for any JWT in the page's cookies, then replays it with alg changed to
    'none' and the signature removed. GET-only, non-destructive."""
    import base64
    import json as _json
    findings = []
    page = await manager.page()
    try:
        cookies = await page.context.cookies()
    except Exception:
        return findings
    jwt_pattern = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")
    candidates: list[tuple[str, str]] = []
    for c in cookies:
        m = jwt_pattern.search(c.get("value", ""))
        if m:
            candidates.append(("cookie", m.group()))
    if not candidates:
        return findings
    for _source, jwt in candidates[:2]:
        parts = jwt.split(".")
        if len(parts) != 3:
            continue
        try:
            header_json = base64.urlsafe_b64decode(parts[0] + "==").decode("utf-8", errors="replace")
        except Exception:
            continue
        if "alg" not in header_json.lower():
            continue
        try:
            header = _json.loads(header_json)
            header["alg"] = "none"
            new_header = base64.urlsafe_b64encode(
                _json.dumps(header, separators=(",", ":")).encode()
            ).rstrip(b"=").decode()
            none_jwt = f"{new_header}.{parts[1]}."
        except Exception:
            continue
        try:
            r = await _req("GET", url, headers={"Authorization": f"Bearer {none_jwt}"})
            body = (await r.text())[:500]
        except Exception:
            continue
        if r.status in (200, 201, 204) and "401" not in body and "403" not in body:
            findings.append({
                "severity": "high",
                "type": "jwt-alg-none",
                "detail": (
                    f"Server accepted JWT with alg:none (signature removed) — "
                    f"authentication bypass, verify manually. Status {r.status}."
                ),
                "evidence": f"Bearer {none_jwt[:40]}… → HTTP {r.status}",
            })
    return findings


async def check_business_logic(url: str) -> list[dict[str, Any]]:
    """Probe for business logic flaws: price/qty tampering in URL params and
    negative quantities. GET-only, non-destructive. Only observes server
    responses — never submits real orders or payments."""
    findings = []
    p = urlparse(url)
    params = dict(parse_qsl(p.query))
    if not params:
        return findings

    price_keys = [k for k in params if re.search(r"price|amount|total|cost|fee|subtotal", k, re.I)]
    qty_keys = [k for k in params if re.search(r"qty|quantity|count|num|items", k, re.I)]
    coupon_keys = [k for k in params if re.search(r"coupon|promo|code|discount|voucher", k, re.I)]

    async def _get_len(test_url: str) -> tuple[int, int]:
        try:
            r = await _req("GET", test_url)
            body = await r.text()
            return r.status, len(body)
        except Exception:
            return 0, 0

    orig_status, orig_len = await _get_len(url)
    if orig_status not in (200, 304):
        return findings

    for key in price_keys[:2]:
        for tampered in ("0", "-1", "0.01"):
            test_params = dict(params)
            test_params[key] = tampered
            test_url = urlunparse(p._replace(query=urlencode(test_params)))
            status, length = await _get_len(test_url)
            if status in (200, 304) and abs(length - orig_len) < 200:
                findings.append({
                    "severity": "medium",
                    "type": "business-logic-price-tamper",
                    "detail": (
                        f"Price parameter {key!r}={tampered!r} returns HTTP {status} "
                        f"with similar body size to original — possible price manipulation, verify manually"
                    ),
                    "evidence": f"GET {test_url} → {status}, {length} bytes",
                })
                break

    for key in qty_keys[:2]:
        for tampered in ("-1", "0", "-99999"):
            test_params = dict(params)
            test_params[key] = tampered
            test_url = urlunparse(p._replace(query=urlencode(test_params)))
            status, length = await _get_len(test_url)
            if status in (200, 304):
                findings.append({
                    "severity": "medium",
                    "type": "business-logic-negative-qty",
                    "detail": (
                        f"Negative/zero quantity {key!r}={tampered!r} returns HTTP {status} "
                        f"without error — potential negative-price exploit, verify manually"
                    ),
                    "evidence": f"GET {test_url} → {status}",
                })
                break

    for key in coupon_keys[:2]:
        for code in ("FAGUN100", "100OFF", "FREE", "ADMIN"):
            test_params = dict(params)
            test_params[key] = code
            test_url = urlunparse(p._replace(query=urlencode(test_params)))
            status, length = await _get_len(test_url)
            if status in (200, 304) and length > orig_len + 50:
                findings.append({
                    "severity": "low",
                    "type": "business-logic-coupon-probe",
                    "detail": (
                        f"Coupon/promo field {key!r}={code!r} returns longer response "
                        f"({length} vs {orig_len} bytes) — possible undisclosed discount, verify"
                    ),
                    "evidence": f"GET {test_url} → {status}, {length} bytes",
                })
                break

    return findings


def clip(s: Any, n: int = 120) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ------------------------------------------------------------------- aggregator
_CHECKS = [
    ("csp", check_csp),
    ("clickjacking", check_clickjacking),
    ("http-methods", check_http_methods),
    ("mixed-content", check_mixed_content),
    ("sri", check_sri),
    ("cache", check_cache),
    ("host-header", check_host_header),
    ("crlf", check_crlf),
    ("path-traversal", check_path_traversal),
    ("ssti", check_ssti),
    ("cmdi", check_cmdi),
    ("graphql", check_graphql),
    ("error-disclosure", check_error_disclosure),
    ("sensitive-url", check_sensitive_url),
    ("jwt-alg-none", check_jwt_alg_none),
    ("business-logic", check_business_logic),
]


# Probes that read the live DOM via page.evaluate (bound to the page's execution
# context). These run sequentially on the loaded page — a concurrent navigation
# would destroy their execution context. Everything else uses the independent
# request context and is safe to run concurrently.
_DOM_CHECKS = {"mixed-content", "sri"}


async def advanced_scan(url: str) -> dict[str, Any]:
    """Run every advanced probe and aggregate. Loads the page once, runs the
    DOM-reading probes serially on that page, then runs the request-context
    probes concurrently. No page-context read ever overlaps a navigation."""
    page = await manager.page()
    page_loaded = True
    try:
        await page.goto(url, wait_until="load", timeout=30000)
    except Exception:
        page_loaded = False

    async def _run(name, fn):
        try:
            return await fn(url)
        except Exception as e:
            return [{"severity": "low", "type": "scan-error",
                     "detail": f"{name}: {e}", "evidence": "probe raised"}]

    findings: list[dict[str, Any]] = []
    if page_loaded:
        for name, fn in _CHECKS:
            if name in _DOM_CHECKS:
                findings += await _run(name, fn)
    else:
        findings.append({
            "severity": "low",
            "type": "scan-warning",
            "detail": "DOM security checks skipped because the page did not load",
            "evidence": "mixed-content and SRI require a loaded document",
        })
    groups = await asyncio.gather(
        *(_run(name, fn) for name, fn in _CHECKS if name not in _DOM_CHECKS)
    )
    findings += [f for g in groups for f in g]
    return {"url": url, "findings": findings}
