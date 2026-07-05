"""Token-lean output formatting.

Browser/QA tools dump huge blobs (pretty JSON, full DOM, long URL lists) that burn
the AI's context. Fagun defaults to TERSE output: compact one-line-per-finding text
instead of indented JSON. That cuts tool-result tokens by ~70% while keeping every
signal the model actually needs. Set FAGUN_TERSE=0 for full JSON.

Token controls:
  FAGUN_TERSE=mini  even shorter one-line summaries for long sessions.
  FAGUN_FINDING_CAP max findings shown per page in terse output (default 40, mini 12).
  FAGUN_PAGE_CAP    max pages rendered in multi-page summaries (default 12, mini 6).
  FAGUN_DETAIL_CHARS finding detail chars (default 100, mini 72).
  FAGUN_URL_CHARS   URL chars (default 60, mini 48).
"""

from __future__ import annotations

import json
import os
from typing import Any

_SEV_TAG = {"high": "H", "medium": "M", "low": "L"}


def is_terse() -> bool:
    return os.environ.get("FAGUN_TERSE", "1") != "0"


def is_mini() -> bool:
    return os.environ.get("FAGUN_TERSE", "1").lower() in {"mini", "2", "ultra"}


def _env_int(name: str, default: int, floor: int = 1, ceiling: int = 1000) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(floor, min(value, ceiling))


def finding_cap() -> int:
    return _env_int("FAGUN_FINDING_CAP", 12 if is_mini() else 40, ceiling=200)


def page_cap() -> int:
    return _env_int("FAGUN_PAGE_CAP", 6 if is_mini() else 12, ceiling=100)


def detail_chars() -> int:
    return _env_int("FAGUN_DETAIL_CHARS", 72 if is_mini() else 100, floor=30, ceiling=500)


def url_chars() -> int:
    return _env_int("FAGUN_URL_CHARS", 48 if is_mini() else 60, floor=24, ceiling=300)


def clip(s: Any, n: int = 120) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def dumps(obj: Any) -> str:
    """Compact JSON (no indent, no spaces) — used when full data is requested."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def _short_url(u: str, keep: int | None = None) -> str:
    u = str(u)
    keep = keep or url_chars()
    return u if len(u) <= keep else "…" + u[-(keep - 1):]


def findings_block(url: str, findings: list[dict[str, Any]], meta: str = "", cap: int | None = None) -> str:
    """One tight line per finding, severity-sorted, capped."""
    cap = finding_cap() if cap is None else cap
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
        suffix = f" ({clip(at, 32 if is_mini() else 40)})" if at and not is_mini() else ""
        lines.append(f"{tag} {f.get('type')}: {clip(f.get('detail'), detail_chars())}{suffix}")
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
    shown = results[:page_cap()]
    for r in shown:
        blocks.append(render_qa(r, terse=True))
    if len(results) > len(shown):
        blocks.append(f"… +{len(results) - len(shown)} more pages (write report_path for full detail)")
    return "\n\n".join(blocks)
