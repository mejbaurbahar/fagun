"""Token-lean output formatting.

Browser/QA tools dump huge blobs (pretty JSON, full DOM, long URL lists) that burn
the AI's context. Fagun defaults to TERSE output: compact one-line-per-finding text
instead of indented JSON. That cuts tool-result tokens by ~70% while keeping every
signal the model actually needs. Set FAGUN_TERSE=0 for full JSON.
"""

from __future__ import annotations

import json
import os
from typing import Any

_SEV_TAG = {"high": "H", "medium": "M", "low": "L"}


def is_terse() -> bool:
    return os.environ.get("FAGUN_TERSE", "1") != "0"


def clip(s: Any, n: int = 120) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def dumps(obj: Any) -> str:
    """Compact JSON (no indent, no spaces) — used when full data is requested."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def _short_url(u: str, keep: int = 60) -> str:
    u = str(u)
    return u if len(u) <= keep else "…" + u[-(keep - 1):]


def findings_block(url: str, findings: list[dict[str, Any]], meta: str = "", cap: int = 40) -> str:
    """One tight line per finding, severity-sorted, capped."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.get("severity", "low")] = counts.get(f.get("severity", "low"), 0) + 1
    head = f"{_short_url(url)}"
    if meta:
        head += f" {meta}"
    head += f" | {len(findings)} findings: {counts['high']}H {counts['medium']}M {counts['low']}L"

    order = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(findings, key=lambda f: order.get(f.get("severity", "low"), 3))
    lines = [head]
    for f in ordered[:cap]:
        tag = _SEV_TAG.get(f.get("severity", "low"), "?")
        at = f.get("at")
        suffix = f" ({clip(at, 40)})" if at else ""
        lines.append(f"{tag} {f.get('type')}: {clip(f.get('detail'), 100)}{suffix}")
    if len(ordered) > cap:
        lines.append(f"… +{len(ordered) - cap} more")
    return "\n".join(lines)


def render_qa(result: dict[str, Any], terse: bool) -> str:
    """Render a single-page QA result."""
    if not terse:
        return dumps(result)
    if not result.get("ok", True):
        fs = result.get("findings", [])
        return findings_block(result.get("url", "?"), fs, meta="LOAD FAILED")
    meta = f"{result.get('status', '?')} {result.get('load_ms', '?')}ms"
    return findings_block(result.get("url", "?"), result.get("findings", []), meta=meta)


def render_multi(results: list[dict[str, Any]], terse: bool, header: str = "") -> str:
    """Render a multi-page result (deep_test / full sweep)."""
    if not terse:
        return dumps(results)
    total = sum(len(r.get("findings", [])) for r in results)
    highs = sum(
        1 for r in results for f in r.get("findings", []) if f.get("severity") == "high"
    )
    blocks = [f"{header} — {len(results)} pages, {total} findings ({highs} high)".strip(" —")]
    for r in results:
        blocks.append(render_qa(r, terse=True))
    return "\n\n".join(blocks)
