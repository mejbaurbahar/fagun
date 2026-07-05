"""Turn QA / UAT results into reports — Markdown, HTML, JSON, or JUnit XML.

Format is chosen by the output file extension (.md/.html/.json/.xml) so the same
`deep_test`/`write_report` call produces a human report, a shareable web page, a
machine-readable dump, or a CI-consumable test artifact.
"""

from __future__ import annotations

import json
from typing import Any
from xml.sax.saxutils import escape

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def _all_findings(results: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for r in results:
        for f in r.get("findings", []):
            out.append((r.get("url", "?"), f))
    return out


def _counts(results: list[dict[str, Any]]) -> dict[str, int]:
    c = {"high": 0, "medium": 0, "low": 0}
    for _, f in _all_findings(results):
        c[f.get("severity", "low")] = c.get(f.get("severity", "low"), 0) + 1
    return c


def _action_steps(r: dict[str, Any]) -> list[dict[str, Any]]:
    steps = r.get("action_trace") or r.get("step_log") or r.get("steps") or []
    return steps if isinstance(steps, list) else []


# ----------------------------------------------------------------- Markdown
def build_markdown(results: list[dict[str, Any]], title: str = "Fagun QA Report",
                   scorecard: dict[str, Any] | None = None) -> str:
    lines = [f"# {title}", ""]
    counts = _counts(results)
    all_findings = _all_findings(results)

    if scorecard:
        lines += _markdown_scorecard(scorecard)

    lines += [
        "## Summary", "",
        f"- Pages checked: **{len(results)}**",
        f"- Findings: **{len(all_findings)}** "
        f"({_SEV_ICON['high']} {counts['high']} high · "
        f"{_SEV_ICON['medium']} {counts['medium']} medium · "
        f"{_SEV_ICON['low']} {counts['low']} low)", "",
    ]

    for r in results:
        lines.append(f"## {r.get('url', '?')}")
        meta = []
        if r.get("status") is not None:
            meta.append(f"status {r['status']}")
        if r.get("load_ms") is not None:
            meta.append(f"{r['load_ms']} ms")
        if r.get("perf_score") is not None:
            meta.append(f"perf {r['perf_score']}/100")
        if r.get("vitals"):
            v = r["vitals"]
            meta.append(f"LCP {v.get('LCP')}ms · CLS {v.get('CLS')} · TBT {v.get('TBT')}ms")
        if meta:
            lines.append(f"_{' · '.join(meta)}_")
        lines.append("")
        steps = _action_steps(r)
        if steps:
            lines += ["### Action timeline", ""]
            for s in steps:
                label = s.get("label") or s.get("action") or f"step {s.get('i', '?')}"
                mark = "✅" if s.get("ok", True) else "❌"
                detail = s.get("detail") or s.get("target") or s.get("url") or ""
                lines.append(f"{s.get('i', len(lines))}. {mark} **{label}** — {detail}")
                extras = []
                if s.get("ms") is not None:
                    extras.append(f"{s['ms']} ms")
                if s.get("console_errors"):
                    extras.append(f"{s['console_errors']} console error(s)")
                if s.get("network_failures"):
                    extras.append(f"{s['network_failures']} failed request(s)")
                if s.get("screenshot"):
                    extras.append(f"screenshot: `{s['screenshot']}`")
                if extras:
                    lines.append(f"   - {' · '.join(extras)}")
            lines.append("")
        fs = sorted(r.get("findings", []), key=lambda f: _SEV_ORDER.get(f.get("severity", "low"), 3))
        if not fs:
            lines.append("✅ No findings.")
        else:
            for f in fs:
                icon = _SEV_ICON.get(f.get("severity", "low"), "•")
                extra = f" _(at {f['at']})_" if f.get("at") else ""
                lines.append(f"- {icon} **{f.get('type')}**: {f.get('detail')}{extra}")
                if f.get("evidence"):
                    lines.append(f"  - _evidence:_ {f['evidence']}")
        lines.append("")

    return "\n".join(lines)


def _markdown_scorecard(sc: dict[str, Any]) -> list[str]:
    lines = ["## 🧭 Product Readiness", "",
             f"**Verdict: {sc['verdict']}** — overall **{sc['overall_score']}/100**",
             "", f"> {sc.get('verdict_reason', '')}", "", "### Category scores", "",
             "| Category | Score | Findings |", "|---|---|---|"]
    for cat, d in sc["categories"].items():
        bar = _bar(d["score"])
        lines.append(f"| {cat} | {bar} {d['score']}/100 | {d['findings']} |")
    lines.append("")
    recs = sc.get("recommendations", [])
    if recs:
        lines += ["### Top recommendations", ""]
        for i, rec in enumerate(recs, 1):
            icon = _SEV_ICON.get(rec["severity"], "•")
            lines.append(f"{i}. {icon} **{rec['type']}** ({rec['count']}×) — {rec['issue']}")
            lines.append(f"   - _why:_ {rec['why']}")
            lines.append(f"   - _fix:_ {rec['fix']}")
        lines.append("")
    return lines


def _bar(score: float) -> str:
    filled = int(round(score / 10))
    return "█" * filled + "░" * (10 - filled)


# --------------------------------------------------------------------- JSON
def build_json(results: list[dict[str, Any]], title: str = "Fagun Report",
               scorecard: dict[str, Any] | None = None) -> str:
    payload = {"title": title, "summary": {"pages": len(results), **_counts(results)},
               "results": results}
    if scorecard:
        payload["readiness"] = scorecard
    return json.dumps(payload, indent=2, default=str)


# ---------------------------------------------------------------- JUnit XML
def build_junit(results: list[dict[str, Any]], title: str = "Fagun") -> str:
    """Each page = a <testsuite>; each finding = a failing <testcase>. Lets CI
    surface Fagun findings in the standard test-report UI."""
    counts = _counts(results)
    total = sum(len(r.get("findings", [])) for r in results)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="{escape(title)}" tests="{total}" '
           f'failures="{counts["high"] + counts["medium"]}">']
    for r in results:
        url = escape(str(r.get("url", "?")))
        fs = r.get("findings", [])
        fails = sum(1 for f in fs if f.get("severity") in ("high", "medium"))
        out.append(f'  <testsuite name="{url}" tests="{max(len(fs),1)}" failures="{fails}">')
        if not fs:
            out.append(f'    <testcase name="{url} — no findings" classname="fagun"/>')
        for f in fs:
            name = escape(f"{f.get('type')}: {f.get('detail','')}"[:180])
            case = f'    <testcase name="{name}" classname="fagun.{escape(f.get("severity","low"))}"'
            if f.get("severity") in ("high", "medium"):
                msg = escape(str(f.get("detail", ""))[:200])
                ev = escape(str(f.get("evidence", "")))
                out.append(case + ">")
                out.append(f'      <failure message="{msg}">{ev}</failure>')
                out.append("    </testcase>")
            else:
                out.append(case + "/>")
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out)


# --------------------------------------------------------------------- HTML
def build_html(results: list[dict[str, Any]], title: str = "Fagun Report",
               scorecard: dict[str, Any] | None = None) -> str:
    counts = _counts(results)
    sev_color = {"high": "#e5484d", "medium": "#f5a623", "low": "#8b8d98"}
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
:root{{color-scheme:light dark}}
body{{font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0e0f13;color:#e6e6e6}}
.wrap{{max-width:960px;margin:0 auto;padding:32px 20px}}
h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:18px;margin:28px 0 10px;border-bottom:1px solid #2a2c35;padding-bottom:6px}}
.sub{{color:#9aa0aa;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}}
.card{{background:#171922;border:1px solid #262933;border-radius:10px;padding:12px 14px}}
.cat{{font-size:13px;color:#c5c8d0}}.score{{font-size:22px;font-weight:700}}
.barw{{height:6px;background:#262933;border-radius:6px;margin-top:8px;overflow:hidden}}
.bar{{height:100%;border-radius:6px}}
.verdict{{font-size:20px;font-weight:700;padding:14px 16px;border-radius:10px;background:#171922;border:1px solid #262933;margin-bottom:8px}}
.f{{padding:8px 12px;border-left:3px solid #333;margin:6px 0;background:#14161d;border-radius:0 8px 8px 0}}
.tag{{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:20px;color:#fff;margin-right:8px}}
.ev{{color:#9aa0aa;font-size:13px;margin-top:3px}}
.rec{{background:#14161d;border:1px solid #262933;border-radius:8px;padding:10px 12px;margin:8px 0}}
code{{background:#20232c;padding:1px 5px;border-radius:5px}}
</style></head><body><div class="wrap">
<h1>🦊 {escape(title)}</h1>
<div class="sub">{len(results)} page(s) · {counts['high']} high · {counts['medium']} medium · {counts['low']} low</div>"""]

    if scorecard:
        vc = {"Ready for Production": "#30a46c", "Ready with Minor Improvements": "#30a46c",
              "Ready After Fixing Medium-Priority Issues": "#f5a623",
              "Not Ready for Production": "#e5484d", "Critical Issues Block Release": "#e5484d"}
        col = vc.get(scorecard["verdict"], "#8b8d98")
        parts.append(f'<div class="verdict" style="border-color:{col}">{escape(scorecard["verdict"])} '
                     f'· {scorecard["overall_score"]}/100</div>')
        parts.append(f'<div class="sub">{escape(scorecard.get("verdict_reason",""))}</div>')
        parts.append('<h2>Category scores</h2><div class="grid">')
        for cat, d in scorecard["categories"].items():
            s = d["score"]
            c = "#30a46c" if s >= 80 else "#f5a623" if s >= 60 else "#e5484d"
            parts.append(f'<div class="card"><div class="cat">{escape(cat)}</div>'
                         f'<div class="score" style="color:{c}">{s}</div>'
                         f'<div class="barw"><div class="bar" style="width:{s}%;background:{c}"></div></div></div>')
        parts.append("</div>")
        recs = scorecard.get("recommendations", [])
        if recs:
            parts.append("<h2>Top recommendations</h2>")
            for rec in recs:
                c = sev_color.get(rec["severity"], "#8b8d98")
                parts.append(f'<div class="rec"><span class="tag" style="background:{c}">{rec["severity"]}</span>'
                             f'<b>{escape(rec["type"])}</b> ({rec["count"]}×) — {escape(rec["issue"])}'
                             f'<div class="ev">Why: {escape(rec["why"])}</div>'
                             f'<div class="ev">Fix: {escape(rec["fix"])}</div></div>')

    for r in results:
        parts.append(f'<h2>{escape(str(r.get("url","?")))}</h2>')
        steps = _action_steps(r)
        if steps:
            parts.append("<h3>Action timeline</h3>")
            for s in steps:
                ok = "ok" if s.get("ok", True) else "blocked"
                label = escape(str(s.get("label") or s.get("action") or f"step {s.get('i', '?')}"))
                detail = escape(str(s.get("detail") or s.get("target") or s.get("url") or ""))
                extras = []
                if s.get("ms") is not None:
                    extras.append(f"{s['ms']} ms")
                if s.get("console_errors"):
                    extras.append(f"{s['console_errors']} console error(s)")
                if s.get("network_failures"):
                    extras.append(f"{s['network_failures']} failed request(s)")
                if s.get("screenshot"):
                    extras.append(f"screenshot: {s['screenshot']}")
                c = "#30a46c" if s.get("ok", True) else "#e5484d"
                parts.append(f'<div class="rec"><span class="tag" style="background:{c}">{escape(ok)}</span>'
                             f'<b>{label}</b> — {detail}'
                             f'<div class="ev">{escape(" · ".join(extras))}</div></div>')
        fs = sorted(r.get("findings", []), key=lambda f: _SEV_ORDER.get(f.get("severity", "low"), 3))
        if not fs:
            parts.append('<div class="sub">✅ No findings.</div>')
        for f in fs:
            c = sev_color.get(f.get("severity", "low"), "#333")
            parts.append(f'<div class="f" style="border-left-color:{c}">'
                         f'<span class="tag" style="background:{c}">{escape(f.get("severity","low"))}</span>'
                         f'<b>{escape(str(f.get("type")))}</b>: {escape(str(f.get("detail","")))}')
            if f.get("evidence"):
                parts.append(f'<div class="ev">evidence: {escape(str(f["evidence"]))}</div>')
            parts.append("</div>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


# ------------------------------------------------------------- format dispatch
def build_report(results: list[dict[str, Any]], title: str = "Fagun Report",
                 fmt: str = "md", scorecard: dict[str, Any] | None = None) -> str:
    fmt = (fmt or "md").lower().lstrip(".")
    if fmt in ("html", "htm"):
        return build_html(results, title, scorecard)
    if fmt == "json":
        return build_json(results, title, scorecard)
    if fmt in ("xml", "junit"):
        return build_junit(results, title)
    return build_markdown(results, title, scorecard)


def write_report(results: list[dict[str, Any]], path: str, title: str = "Fagun Report",
                 scorecard: dict[str, Any] | None = None) -> str:
    """Write a report, picking the format from the file extension."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "md"
    content = build_report(results, title, fmt=ext, scorecard=scorecard)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path
