"""Turn QA results into a Markdown report."""

from __future__ import annotations

from typing import Any

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def build_markdown(results: list[dict[str, Any]], title: str = "Fagun QA Report") -> str:
    lines = [f"# {title}", ""]
    all_findings: list[tuple[str, dict[str, Any]]] = []
    for r in results:
        for f in r.get("findings", []):
            all_findings.append((r.get("url", "?"), f))

    counts = {"high": 0, "medium": 0, "low": 0}
    for _, f in all_findings:
        counts[f.get("severity", "low")] = counts.get(f.get("severity", "low"), 0) + 1

    lines += [
        "## Summary",
        "",
        f"- Pages checked: **{len(results)}**",
        f"- Findings: **{len(all_findings)}** "
        f"({_SEV_ICON['high']} {counts['high']} high · "
        f"{_SEV_ICON['medium']} {counts['medium']} medium · "
        f"{_SEV_ICON['low']} {counts['low']} low)",
        "",
    ]

    for r in results:
        lines.append(f"## {r.get('url', '?')}")
        meta = []
        if r.get("status") is not None:
            meta.append(f"status {r['status']}")
        if r.get("load_ms") is not None:
            meta.append(f"{r['load_ms']} ms")
        if meta:
            lines.append(f"_{' · '.join(meta)}_")
        lines.append("")
        fs = sorted(
            r.get("findings", []), key=lambda f: _SEV_ORDER.get(f.get("severity", "low"), 3)
        )
        if not fs:
            lines.append("✅ No findings.")
        else:
            for f in fs:
                icon = _SEV_ICON.get(f.get("severity", "low"), "•")
                extra = f" _(at {f['at']})_" if f.get("at") else ""
                lines.append(f"- {icon} **{f.get('type')}**: {f.get('detail')}{extra}")
        lines.append("")

    return "\n".join(lines)
