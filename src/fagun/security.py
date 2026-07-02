"""Active-but-safe security checks — the classes bug-bounty hunters actually find.

Every probe here is NON-DESTRUCTIVE: GET/HEAD only, unique harmless markers, no
data mutation, no attacks against third parties. Findings are reported as
"potential — verify manually" where a probe can't be 100% sure. Only ever run
against a target the user is authorized to test.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .browser import manager

MARKER = "fagunXSS9271"

# Files that should never be publicly reachable.
_SENSITIVE_PATHS = [
    "/.git/config", "/.git/HEAD", "/.env", "/.env.local", "/.env.production",
    "/config.php.bak", "/wp-config.php.bak", "/.aws/credentials", "/.ssh/id_rsa",
    "/.DS_Store", "/backup.zip", "/backup.sql", "/db.sql", "/dump.sql",
    "/phpinfo.php", "/.svn/entries", "/.htaccess", "/server-status",
    "/actuator", "/actuator/env", "/actuator/health", "/api/swagger.json",
    "/swagger-ui.html", "/graphql", "/.well-known/security.txt",
    "/composer.json", "/package.json", "/Dockerfile", "/docker-compose.yml",
]

_SENSITIVE_CONTENT = [
    (re.compile(r"\[core\]|repositoryformatversion"), ".git repo exposed"),
    (re.compile(r"^[A-Z0-9_]+=.+", re.M), "env file with secrets"),
    (re.compile(r"aws_secret_access_key", re.I), "AWS credentials"),
    (re.compile(r"BEGIN (RSA|OPENSSH|PRIVATE) "), "private key"),
    (re.compile(r"phpinfo\(\)|PHP Version"), "phpinfo() exposed"),
    (re.compile(r"Index of /"), "directory listing"),
]

# Secret patterns in page/JS source.
_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"sk_live_[0-9a-zA-Z]{24,}"), "Stripe live secret key"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API key"),
    (re.compile(r"ghp_[0-9A-Za-z]{36}"), "GitHub token"),
    (re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT"),
]

_SQL_ERRORS = re.compile(
    r"SQL syntax|mysql_fetch|ORA-\d{5}|PostgreSQL.*ERROR|SQLite3::|"
    r"Unclosed quotation mark|Microsoft OLE DB|valid MySQL result",
    re.I,
)


async def _get(url: str, headers: dict | None = None):
    page = await manager.page()
    return await page.request.get(url, headers=headers or {}, timeout=15000, fail_on_status_code=False)


async def scan_exposed_files(base_url: str) -> list[dict[str, Any]]:
    p = urlparse(base_url)
    root = f"{p.scheme}://{p.netloc}"
    findings = []
    for path in _SENSITIVE_PATHS:
        try:
            r = await _get(root + path)
        except Exception:
            continue
        if r.status != 200:
            continue
        body = ""
        try:
            body = (await r.text())[:4000]
        except Exception:
            pass
        matched = next((msg for rx, msg in _SENSITIVE_CONTENT if rx.search(body)), None)
        # Some paths are sensitive by mere existence (200) even without content match.
        always = path in ("/.env", "/.git/config", "/.git/HEAD", "/.aws/credentials", "/.ssh/id_rsa")
        if matched or always:
            findings.append({
                "severity": "high",
                "type": "exposed-file",
                "detail": f"{root + path} → 200 ({matched or 'sensitive path reachable'})",
            })
    return findings


async def scan_secrets(url: str) -> list[dict[str, Any]]:
    page = await manager.page()
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    html = await page.content()
    scripts = await page.eval_on_selector_all(
        "script[src]", "els => els.map(e => e.src)"
    )
    blobs = [html]
    for src in scripts[:15]:
        try:
            r = await _get(src)
            if r.status == 200:
                blobs.append((await r.text())[:200000])
        except Exception:
            pass
    findings = []
    seen = set()
    for blob in blobs:
        for rx, label in _SECRET_PATTERNS:
            for m in rx.findall(blob):
                token = m if isinstance(m, str) else m[0]
                key = (label, token[:12])
                if key in seen:
                    continue
                seen.add(key)
                # A bare JWT in client code is often a *public* token (anon API
                # keys, feature flags) — reflect uncertainty instead of crying
                # "high". Real credential formats (AKIA…, sk_live_…) stay high.
                if label == "JWT":
                    findings.append({
                        "severity": "medium",
                        "type": "leaked-secret",
                        "detail": f"JWT in page/JS: {token[:10]}… — verify it is not a "
                                  f"privileged/server token (public anon tokens are OK)",
                    })
                else:
                    findings.append({
                        "severity": "high",
                        "type": "leaked-secret",
                        "detail": f"{label} in page/JS: {token[:10]}…",
                    })
    return findings


async def check_cors(url: str) -> list[dict[str, Any]]:
    evil = "https://fagun-evil.example"
    try:
        r = await _get(url, headers={"Origin": evil})
    except Exception:
        return []
    h = {k.lower(): v for k, v in r.headers.items()}
    acao = h.get("access-control-allow-origin", "")
    acac = h.get("access-control-allow-credentials", "")
    findings = []
    if acao == evil and acac.lower() == "true":
        findings.append({"severity": "high", "type": "cors-misconfig",
                         "detail": "Reflects arbitrary Origin WITH credentials — account data theft risk"})
    elif acao == "*" and acac.lower() == "true":
        findings.append({"severity": "medium", "type": "cors-misconfig",
                         "detail": "ACAO:* with credentials"})
    elif acao == evil:
        findings.append({"severity": "medium", "type": "cors-misconfig",
                         "detail": "Reflects arbitrary Origin (no creds) — verify impact"})
    return findings


async def check_cookies(url: str) -> list[dict[str, Any]]:
    try:
        r = await _get(url)
    except Exception:
        return []
    findings = []
    # Playwright merges headers; check the raw set-cookie via headers_array if available.
    try:
        arr = await r.headers_array()
        cookies = [v["value"] for v in arr if v["name"].lower() == "set-cookie"]
    except Exception:
        sc = r.headers.get("set-cookie", "")
        cookies = [sc] if sc else []
    for c in cookies:
        name = c.split("=", 1)[0]
        low = c.lower()
        flags = []
        if "secure" not in low:
            flags.append("no Secure")
        if "httponly" not in low:
            flags.append("no HttpOnly")
        if "samesite" not in low:
            flags.append("no SameSite")
        if flags:
            findings.append({"severity": "low", "type": "cookie-flags",
                             "detail": f"Cookie {name}: {', '.join(flags)}"})
    return findings


def _with_param(url: str, key: str, value: str) -> str:
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    q[key] = value
    return urlunparse(p._replace(query=urlencode(q)))


async def probe_reflection(url: str) -> list[dict[str, Any]]:
    """Inject a harmless marker into query params; flag unescaped reflection (XSS candidate)."""
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)] or ["q", "search", "s", "name", "redirect"]
    findings = []
    payload = f'"><{MARKER}>'
    for key in params[:6]:
        test = _with_param(url, key, payload)
        try:
            r = await _get(test)
            body = await r.text()
        except Exception:
            continue
        if f"<{MARKER}>" in body:
            findings.append({"severity": "high", "type": "xss-reflection",
                             "detail": f"param {key!r} reflects unescaped '<{MARKER}>' — potential XSS, verify"})
        elif MARKER in body and payload in body:
            findings.append({"severity": "medium", "type": "reflection",
                             "detail": f"param {key!r} reflects input (partially encoded) — verify XSS"})
    return findings


async def probe_open_redirect(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)]
    candidates = params + ["next", "url", "redirect", "return", "returnUrl", "dest", "continue"]
    findings = []
    target = "https://fagun-redirect.example/"
    for key in list(dict.fromkeys(candidates))[:8]:
        test = _with_param(url, key, target)
        try:
            page = await manager.page()
            r = await page.request.get(test, max_redirects=0, timeout=12000, fail_on_status_code=False)
        except Exception:
            continue
        loc = {k.lower(): v for k, v in r.headers.items()}.get("location", "")
        if loc.startswith(target) or loc.startswith("//fagun-redirect"):
            findings.append({"severity": "medium", "type": "open-redirect",
                             "detail": f"param {key!r} → redirects to external {loc[:60]}"})
    return findings


async def probe_sqli_error(url: str) -> list[dict[str, Any]]:
    p = urlparse(url)
    params = [k for k, _ in parse_qsl(p.query)]
    if not params:
        return []
    findings = []
    for key in params[:5]:
        test = _with_param(url, key, "'")
        try:
            r = await _get(test)
            body = await r.text()
        except Exception:
            continue
        if _SQL_ERRORS.search(body):
            findings.append({"severity": "high", "type": "sqli-error",
                             "detail": f"param {key!r} triggers SQL error with a single quote — potential SQLi"})
    return findings


async def security_scan(url: str) -> dict[str, Any]:
    """Run all safe security probes and aggregate findings.

    scan_secrets is the only probe that navigates the shared page (goto + read
    DOM), so it runs ALONE first — no page-context operation ever overlaps a
    navigation. The remaining probes use the navigation-independent request
    context and run concurrently. This keeps the parallelism safe by
    construction, not by an implicit "only one navigator" assumption."""

    async def _run(name, fn):
        try:
            return await fn(url)
        except Exception as e:
            return [{"severity": "low", "type": "scan-error", "detail": f"{name}: {e}"}]

    findings: list[dict[str, Any]] = await _run("secrets", scan_secrets)
    parallel = [
        ("exposed-files", scan_exposed_files),
        ("cors", check_cors),
        ("cookies", check_cookies),
        ("reflection", probe_reflection),
        ("open-redirect", probe_open_redirect),
        ("sqli", probe_sqli_error),
    ]
    groups = await asyncio.gather(*(_run(name, fn) for name, fn in parallel))
    findings += [f for g in groups for f in g]
    return {"url": url, "findings": findings}
