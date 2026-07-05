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


def _coverage(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in results:
        c = r.get("coverage")
        if isinstance(c, dict):
            return c
    return None


def _jira_ticket(url: str, f: dict[str, Any], idx: int) -> dict[str, Any]:
    sev = str(f.get("severity", "low")).lower()
    priority = {"high": "Highest", "medium": "High", "low": "Medium"}.get(sev, "Medium")
    severity = {"high": "Critical", "medium": "Major", "low": "Minor"}.get(sev, "Minor")
    title = f"{f.get('type', 'bug')} on {url}"
    detail = str(f.get("detail", ""))
    evidence = str(f.get("evidence") or f.get("screenshot") or "")
    steps = f.get("steps") or [
        f"Open {url}",
        "Reproduce the affected flow or field described in the finding.",
        "Observe the issue and compare against the expected behavior.",
    ]
    if not isinstance(steps, list):
        steps = [str(steps)]
    return {
        "key": f"FAGUN-{idx}",
        "url": url,
        "summary": title[:180],
        "priority": priority,
        "severity": severity,
        "severity_raw": sev,
        "issue_type": "Bug",
        "description": detail,
        "steps": [str(s) for s in steps],
        "observed": detail,
        "expected": _expected_for(f),
        "impact": _impact_for(f),
        "evidence": evidence,
        "screenshot": str(f.get("screenshot") or ""),
        "fix": _fix_for(f),
        "frequency": str(f.get("frequency") or "Always (100%)"),
        "ui_error": str(f.get("ui_error") or ""),
        "console_error": str(f.get("console_error") or f.get("console") or ""),
        "request": str(f.get("request") or f.get("network_request") or ""),
        "status": str(f.get("status") or f.get("network_status") or ""),
        "response": f.get("response") or f.get("network_response") or "",
        "preconditions": f.get("preconditions") or ["Target is reachable.", "Tester is authorized to test this environment."],
    }


def _ticket_markdown(t: dict[str, Any], url: str) -> list[str]:
    response = t["response"]
    if isinstance(response, (dict, list)):
        response = json.dumps(response, indent=2, default=str)
    response = str(response)
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(t["steps"], 1))
    preconditions = "\n".join(f"{i}. {s}" for i, s in enumerate(t["preconditions"], 1))
    screenshot = t["screenshot"] or t["evidence"] or "Attach Fagun screenshot or report evidence."
    return [
        f"### {t['key']} — {t['summary']}",
        "",
        "# 🐞 Bug Report",
        "",
        "## Summary",
        t["summary"],
        "",
        "---",
        "",
        "## Environment",
        "",
        "- Environment: Test target / staging unless otherwise specified",
        f"- URL: {url}",
        "- Browser: Chromium / Chrome via Fagun",
        "- Browser Version: Captured by local runner if available",
        "- Device: Desktop browser unless persona says otherwise",
        "- OS: Local tester machine",
        "- User Role: Current browser session / unauthenticated unless logged in",
        "- Build/Commit: Not provided by target",
        "- API Version (if applicable): Not provided by target",
        "",
        "---",
        "",
        "## Preconditions",
        "",
        preconditions,
        "",
        "---",
        "",
        "## Steps to Reproduce",
        "",
        steps,
        "",
        "---",
        "",
        "## Actual Result",
        "",
        t["observed"],
        "",
        "---",
        "",
        "## Expected Result",
        "",
        t["expected"],
        "",
        "---",
        "",
        "## Frequency",
        "",
        f"- [x] {t['frequency']}",
        "- [ ] Often",
        "- [ ] Sometimes",
        "- [ ] Rarely",
        "- [ ] Unable to Reproduce",
        "",
        "---",
        "",
        "## Severity",
        "",
        f"- {t['severity']}",
        "",
        "---",
        "",
        "## Priority",
        "",
        f"- {t['priority']}",
        "",
        "---",
        "",
        "## Impact",
        "",
        t["impact"],
        "",
        "---",
        "",
        "## Error Details",
        "",
        "### UI Error",
        "",
        "```",
        t["ui_error"] or t["description"] or "No separate UI error text captured.",
        "```",
        "",
        "### Console Error",
        "",
        "```javascript",
        t["console_error"] or "No console error captured for this finding.",
        "```",
        "",
        "### Network Request",
        "",
        "Request",
        "",
        "```",
        t["request"] or t["evidence"] or "No specific request captured for this finding.",
        "```",
        "",
        "Status",
        "",
        "```",
        t["status"] or "Not captured / not applicable.",
        "```",
        "",
        "Response",
        "",
        "```json",
        response or "{}",
        "```",
        "",
        "---",
        "",
        "## Screenshots / Screen Recording",
        "",
        f"- {screenshot}",
        "",
        "---",
        "",
        "## Additional Notes",
        "",
        f"- Suggested fix: {t['fix']}",
        "- Workaround: Not identified unless noted above.",
        "- Suspected root cause: Derived from Fagun evidence; confirm in source/logs.",
        "- Related issue: Not linked.",
        "- Regression: Unknown.",
        "",
    ]


def _expected_for(f: dict[str, Any]) -> str:
    typ = str(f.get("type", ""))
    if "form" in typ or "validation" in typ:
        return "Invalid, empty, boundary, and malicious inputs are rejected with clear inline errors; valid inputs are accepted."
    if "keyboard" in typ or "a11y" in typ:
        return "All users can identify, reach, and operate the control with keyboard and assistive technology."
    if "request" in typ or "network" in typ:
        return "Required requests complete successfully or fail gracefully without breaking the user journey."
    if "sec" in typ or "xss" in typ or "csp" in typ:
        return "Security controls prevent credential leakage, injection, and browser-side exploit paths."
    return "The feature completes the user/business workflow without errors or confusion."


def _impact_for(f: dict[str, Any]) -> str:
    sev = f.get("severity", "low")
    if sev == "high":
        return "Can block a core journey, leak sensitive data, or create a serious trust/security risk."
    if sev == "medium":
        return "Degrades usability, reliability, or confidence for a meaningful user segment."
    return "Polish or hardening issue that should be fixed before production maturity."


def _fix_for(f: dict[str, Any]) -> str:
    typ = str(f.get("type", ""))
    if "form-security" in typ:
        return "Use POST over HTTPS for sensitive submissions; never place passwords or tokens in query strings."
    if "form-validation" in typ:
        return "Add client and server validation for required, invalid, negative, boundary, special-character, and injection cases."
    if "a11y-inputLabel" in typ or "form-a11y" in typ:
        return "Add explicit labels or aria-labelledby/aria-label and verify with a screen reader."
    if "keyboard" in typ:
        return "Fix focus order and escape/Tab handling; verify full keyboard journey."
    if "sec-header" in typ:
        return "Add hardened CSP/HSTS/frame/referrer/content-type policies at the edge or app server."
    return "Fix the root cause, add a regression test, and rerun the same Fagun scenario."


# ----------------------------------------------------------------- Markdown
def build_markdown(results: list[dict[str, Any]], title: str = "Fagun QA Report",
                   scorecard: dict[str, Any] | None = None) -> str:
    lines = [f"# {title}", ""]
    counts = _counts(results)
    all_findings = _all_findings(results)

    if scorecard:
        lines += _markdown_scorecard(scorecard)

    coverage = _coverage(results)
    lines += [
        "## Summary", "",
        f"- Pages checked: **{len(results)}**",
        f"- Findings: **{len(all_findings)}** "
        f"({_SEV_ICON['high']} {counts['high']} high · "
        f"{_SEV_ICON['medium']} {counts['medium']} medium · "
        f"{_SEV_ICON['low']} {counts['low']} low)", "",
    ]
    if coverage:
        lines += [
            "## Coverage", "",
            f"- Status: **{coverage.get('status', 'unknown')}**",
            f"- Pages crawled: **{coverage.get('crawl_pages', '?')}**",
            f"- Pages tested: **{coverage.get('pages_tested', len(results))}**",
            f"- Reason: {coverage.get('reason', '')}",
        ]
        not_tested = coverage.get("not_tested") or []
        if not_tested:
            lines.append("- Not tested:")
            lines.extend(f"  - {x}" for x in not_tested)
        tested = coverage.get("tested_urls") or []
        if tested:
            lines.append("- Tested URLs:")
            lines.extend(f"  - {x}" for x in tested)
        lines.append("")

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
        matrix = r.get("scenario_matrix") or []
        if matrix:
            lines += ["### Form Scenario Matrix", ""]
            for m in matrix:
                s = m.get("summary", {})
                lines.append(f"- **{m.get('form')} → {m.get('field')}** ({m.get('type')})")
                lines.append(f"  - cases: {s.get('total', 0)} · browser-valid: {s.get('valid', 0)} · browser-invalid: {s.get('invalid', 0)} · accepted reject-cases: {s.get('accepted_reject_cases', 0)}")
                for c in (m.get("cases") or [])[:18]:
                    lines.append(f"  - `{c.get('category')}` {c.get('label')} → expect {c.get('expect')} / browser_valid={c.get('browser_valid')}")
                if len(m.get("cases") or []) > 18:
                    lines.append(f"  - … +{len(m['cases']) - 18} more cases")
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
                if f.get("screenshot"):
                    lines.append(f"  - _screenshot:_ `{f['screenshot']}`")
        lines.append("")

    tickets = [_jira_ticket(url, f, i) for i, (url, f) in enumerate(all_findings, 1)]
    if tickets:
        lines += ["## Jira Bug Tickets", ""]
        for t in tickets:
            lines += _ticket_markdown(t, t["url"])

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

    coverage = _coverage(results)
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
    if coverage:
        tested = "".join(f"<li>{escape(str(x))}</li>" for x in coverage.get("tested_urls", []))
        not_tested = "".join(f"<li>{escape(str(x))}</li>" for x in coverage.get("not_tested", []))
        parts.append("<h2>Coverage</h2>")
        parts.append(f'<div class="rec"><span class="tag">{escape(str(coverage.get("status", "unknown")))}</span>'
                     f'<b>{escape(str(coverage.get("pages_tested", len(results))))} tested / '
                     f'{escape(str(coverage.get("crawl_pages", "?")))} crawled</b>'
                     f'<div class="ev">{escape(str(coverage.get("reason", "")))}</div>'
                     f'<div class="ev"><b>Tested URLs</b><ul>{tested}</ul></div>'
                     f'<div class="ev"><b>Not tested</b><ul>{not_tested}</ul></div></div>')

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
        matrix = r.get("scenario_matrix") or []
        if matrix:
            parts.append("<h3>Form Scenario Matrix</h3>")
            for m in matrix:
                s = m.get("summary", {})
                parts.append(f'<div class="rec"><b>{escape(str(m.get("form")))} → {escape(str(m.get("field")))}</b>'
                             f'<div class="ev">type: {escape(str(m.get("type")))} · cases: {s.get("total", 0)} · '
                             f'valid: {s.get("valid", 0)} · invalid: {s.get("invalid", 0)} · accepted reject-cases: {s.get("accepted_reject_cases", 0)}</div></div>')
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
            if f.get("screenshot"):
                parts.append(f'<div class="ev">screenshot: {escape(str(f["screenshot"]))}</div>')
            parts.append("</div>")
    all_findings = _all_findings(results)
    if all_findings:
        parts.append("<h2>Jira Bug Tickets</h2>")
        for i, (url, f) in enumerate(all_findings, 1):
            t = _jira_ticket(url, f, i)
            steps = "\n".join(f"{n}. {s}" for n, s in enumerate(t["steps"], 1))
            preconditions = "\n".join(f"{n}. {s}" for n, s in enumerate(t["preconditions"], 1))
            response = t["response"]
            if isinstance(response, (dict, list)):
                response = json.dumps(response, indent=2, default=str)
            parts.append(f'<div class="rec"><span class="tag">{escape(t["priority"])}</span>'
                         f'<b>{escape(t["key"])} — {escape(t["summary"])}</b>'
                         f'<div class="ev"><b>Environment:</b> URL {escape(url)} · Browser Chromium/Chrome via Fagun · User role current session/unauthenticated unless logged in</div>'
                         f'<div class="ev"><b>Preconditions:</b><br><pre>{escape(preconditions)}</pre></div>'
                         f'<div class="ev"><b>Steps to Reproduce:</b><br><pre>{escape(steps)}</pre></div>'
                         f'<div class="ev"><b>Actual Result:</b> {escape(t["observed"])}</div>'
                         f'<div class="ev"><b>Expected Result:</b> {escape(t["expected"])}</div>'
                         f'<div class="ev"><b>Frequency:</b> {escape(t["frequency"])}</div>'
                         f'<div class="ev"><b>Severity:</b> {escape(t["severity"])} · <b>Priority:</b> {escape(t["priority"])}</div>'
                         f'<div class="ev"><b>Impact:</b> {escape(t["impact"])}</div>'
                         f'<div class="ev"><b>UI Error:</b><pre>{escape(t["ui_error"] or t["description"] or "No separate UI error text captured.")}</pre></div>'
                         f'<div class="ev"><b>Console Error:</b><pre>{escape(t["console_error"] or "No console error captured for this finding.")}</pre></div>'
                         f'<div class="ev"><b>Network Request:</b><pre>{escape(t["request"] or t["evidence"] or "No specific request captured for this finding.")}</pre></div>'
                         f'<div class="ev"><b>Status:</b><pre>{escape(t["status"] or "Not captured / not applicable.")}</pre></div>'
                         f'<div class="ev"><b>Response:</b><pre>{escape(str(response) or "{}")}</pre></div>'
                         f'<div class="ev"><b>Screenshots / Recording:</b> {escape(t["screenshot"] or t["evidence"] or "Attach Fagun screenshot or report evidence.")}</div>'
                         f'<div class="ev"><b>Additional Notes:</b> Suggested fix: {escape(t["fix"])} · Regression: Unknown</div></div>')
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
