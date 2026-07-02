"""Scope guard — keep active probes on authorized hosts only.

Fagun sends *active* requests (XSS/SSTI/CRLF/LFI/host-header probes, form
submits). Firing those at a host you're not allowed to test is a legal and
safety problem. This module gates every outbound target against an optional
allow/deny list so a stray crawl link or a mistyped URL can't reach an
out-of-scope host.

Configuration (env, comma-separated hostnames; subdomains included):
  FAGUN_SCOPE       allow-list. When set, ONLY these hosts (and subdomains)
                    may be probed; everything else is refused.
  FAGUN_SCOPE_DENY  deny-list. These hosts are always refused, even if the
                    allow-list would permit them.

Default (neither set) allows every host — same behaviour as before, so nothing
breaks until a user opts in. file:// and about: targets are always allowed
(local fixtures / blank pages carry no host).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def _hosts(env: str) -> set[str]:
    return {h.strip().lower() for h in os.environ.get(env, "").split(",") if h.strip()}


def _match(host: str, rules: set[str]) -> bool:
    return any(host == r or host.endswith("." + r) for r in rules)


def in_scope(url: str) -> bool:
    """True if `url`'s host is allowed to receive requests."""
    host = (urlparse(url).hostname or "").lower()
    if not host:  # file://, about:blank, data: — no remote host to protect
        return True
    if _match(host, _hosts("FAGUN_SCOPE_DENY")):
        return False
    allow = _hosts("FAGUN_SCOPE")
    if not allow:
        return True
    return _match(host, allow)


def guard(url: str) -> None:
    """Raise if `url` is out of scope. Call before any active request."""
    if not in_scope(url):
        host = urlparse(url).hostname or url
        raise PermissionError(
            f"{host!r} is out of scope. Set FAGUN_SCOPE to include it "
            f"(current allow-list: {os.environ.get('FAGUN_SCOPE') or 'none'})."
        )


def is_configured() -> bool:
    """True if any scope rule is active (used to decide whether to enforce)."""
    return bool(_hosts("FAGUN_SCOPE") or _hosts("FAGUN_SCOPE_DENY"))
