"""Model-agnostic AutoQA workflow guidance.

Fagun does not call an LLM provider directly. The host AI client plans the test
with its own model, then uses Fagun MCP tools to execute browser actions. That
keeps Fagun usable from Claude, Codex, Antigravity, Cursor, Windsurf, and local
models without asking the end user for Groq/OpenAI/Anthropic/Gemini API keys.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


FAGUN_HOME_URL = "https://mejbaurbahar.github.io/fagun/"
FAGUN_DOCS_URL = "https://mejbaurbahar.github.io/fagun/docs.html"
FAGUN_GITHUB_URL = "https://github.com/mejbaurbahar/fagun"
FAGUN_PYPI_URL = "https://pypi.org/project/fagun/"


AUTOQA_WORKFLOW = """You are running AutoQA through Fagun.

Operating rule:
- Do not ask the user for Groq, OpenAI, Anthropic, Gemini, or other model API keys.
- Use the current AI client/model to reason and plan.
- Treat Fagun as the main orchestration tool. When Fagun setup has registered supporting MCPs, call those MCPs as needed during the Fagun run: Chrome DevTools MCP for the user's default Chrome, Jam MCP for screenshots/screen recordings, fetch/docs/security MCPs for supporting evidence.
- Only test public or explicitly authorized targets.
- Never perform destructive actions or submit real payments/orders unless the user explicitly confirms a safe test environment.

Workflow:
1. Restate the target URL, objective, assumptions, and safety constraints.
2. Open the target with Chrome DevTools MCP / the user's default Chrome when the client exposes it. Do not open Fagun's own browser unless Chrome MCP is unavailable or fails, and record that fallback in the report.
3. Call product_map(url) unless the user already gave exact steps.
4. Create a compact test plan with 3-12 steps. Prefer observable assertions.
5. Execute the plan with Chrome DevTools MCP actions first; use Fagun navigate, click, fill, press_key, screenshot, evaluate_js, get_console, and get_network only as needed.
6. After each important action, capture evidence for that exact Interactive Test Flow step: URL, page title/text signal, Jam MCP screenshot or screen-recording URL when available, fallback screenshot path, console errors, and failed network calls.
7. If selectors fail, inspect the page and adapt once before declaring a step blocked.
8. For reproducible bugs, use Jam MCP when available to capture a screenshot or screen recording with console/network evidence; attach the Jam link or recording URL to both the finding and the related Interactive Test Flow step.
9. Always generate an HTML report with autoqa_write_html_report before the final chat answer, then open the returned Report URL with Chrome DevTools MCP / default Chrome. Do not rely on Fagun's fallback browser for report display unless Chrome MCP is unavailable.
10. Return a Fagun-style summary with verdict, report path, steps run, evidence, bugs found, fixes, and residual risk.

Phase upgrades built into Fagun:
- Phase 1 Run Memory: autoqa_write_html_report stores structured run JSON and an index under reports/runs/ by default.
- Phase 2 Replay / Regression: use autoqa_replay_prompt(run_ref) to replay a stored flow and compare the new run to the old one.
- Phase 3 Report Comparison: use autoqa_compare_runs(before_ref, after_ref) to show fixed, still-open, and new findings.
- Phase 4 Power Modes: use existing Fagun tools for evidence timeline fields, test data generation, a11y_audit + keyboard_walk, map_api/deep_test(include_api_map=true), auth_status/session tools, and optional LangGraph host orchestration.
- Do not add Jira/GitHub/Linear/Notion export in this workflow.

Supporting MCP routing during Fagun runs:
- Fagun is the main tool and owns the test plan, verdict, report, and final answer.
- chrome-devtools: primary browser for user-default Chrome, logged-in sessions, DevTools network/console/performance, and opening the final report.
- jam: capture screenshot or screen recording evidence for every important Interactive Test Flow step and every reproducible bug.
- playwright: use when software testing needs isolated/headless browser automation, multi-page or multi-context checks, cross-browser-style verification, stable screenshots, file downloads/uploads, PDF/export checks, tracing/video-style automation, or repeatable regression journeys.
- mcp-fetch: fetch static pages, robots/sitemap, docs, API responses, headers, and lightweight page content without disturbing the live browser session.
- context7: pull current framework/library docs before recommending fixes that depend on library behavior, APIs, or version-specific guidance.
- virustotal: optional, key-backed URL/domain/IP reputation evidence for authorized security checks only.
- shodan: optional, key-backed exposure, open-port, service, and CVE intelligence for authorized assets only.
- LangGraph or similar host-side orchestration frameworks: use when a wrapper needs durable state, branching, retries, reviewer loops, or multi-agent testing plans. Keep Fagun as the execution/reporting layer and include any orchestrator name in the report source.
- If a supporting MCP is unavailable, continue with Fagun's own tools and record the fallback in the report source/evidence.

Suggested plan JSON shape:
{
  "test_name": "short name",
  "objective": "what the test verifies",
  "steps": [
    {
      "step_number": 1,
      "action": "navigate|click|fill|press_key|assert_text|assert_url|screenshot|inspect",
      "target": "URL, text, selector, key, or expected text",
      "value": "text to type or null",
      "why": "what this proves"
    }
  ],
  "success_criteria": "clear pass/fail rule"
}

Useful Fagun tools:
- Chrome DevTools MCP open/new page tools when available, before any Fagun fallback browser.
- Jam MCP for every important step screenshot/screen recording, bug screenshots, console/network capture, and shareable evidence links.
- Playwright MCP for isolated repeatable automation, multi-context browser testing, downloads/uploads, trace/video-style runs, and cross-browser-style verification.
- MCP Fetch for lightweight content/API/header fetching without changing browser state.
- Context7 MCP for current framework/library docs when fixes need implementation guidance.
- VirusTotal/Shodan MCPs for optional authorized security intelligence when API keys are configured.
- LangGraph or similar host-side orchestration for complex stateful test workflows, if the host app already uses it.
- product_map(url) for business context and recommended journeys
- navigate(url), click(target), fill(selector, value), press_key(key)
- screenshot(full_page=true) for visual evidence
- evaluate_js(code) for page text, title, DOM checks, and custom assertions
- get_console(only_errors=true), get_network(only_problems=true)
- autoqa_write_html_report(project_name, target_url, goal, result_json_or_text) at the end; open the returned Report URL with Chrome DevTools MCP/default Chrome
- autoqa_list_runs(limit), autoqa_replay_prompt(run_ref), autoqa_compare_runs(before_ref, after_ref) for memory, replay, and before/after regression analysis
- autoqa_power_plan(url, goal) for Phase 4 evidence timeline, test data, accessibility, API mapping, smart auth, and optional LangGraph orchestration
- run_qa(url), full_qa_sweep(url), deep_test(url) when the user wants broad coverage

Assertion helpers via evaluate_js:
- document.title
- document.body.innerText.includes("expected text")
- location.href.includes("expected-fragment")
- [...document.querySelectorAll("button,a,input")].map(e => e.innerText || e.value || e.placeholder).filter(Boolean)
"""


def workflow_prompt(url: str = "", goal: str = "") -> str:
    """Return model-neutral instructions for running AutoQA via Fagun."""
    context = []
    if url:
        context.append(f"Target URL: {url}")
    if goal:
        context.append(f"Goal: {goal}")
    if not context:
        return AUTOQA_WORKFLOW
    return AUTOQA_WORKFLOW + "\n\nCurrent task:\n" + "\n".join(context)


def plan_template(url: str = "", goal: str = "") -> str:
    """Return a JSON template the host AI can fill before executing tools."""
    template = {
        "test_name": "",
        "target_url": url,
        "objective": goal,
        "assumptions": [],
        "steps": [
            {
                "step_number": 1,
                "action": "navigate",
                "target": url or "https://example.com",
                "value": None,
                "why": "Open the target page.",
            }
        ],
        "success_criteria": "",
        "evidence_to_collect": ["screenshot", "jam_url", "screen_recording", "console_errors", "network_failures", "url", "title"],
    }
    return json.dumps(template, indent=2)


def power_plan_prompt(url: str = "", goal: str = "") -> str:
    """Return a phase-4 power workflow using existing Fagun capabilities."""
    target = url or "<target-url>"
    objective = goal or "deep product readiness, regression, and bug validation"
    return f"""Run Fagun Phase 4 Power Mode.

Target: {target}
Objective: {objective}

Use Fagun as the execution/reporting layer and skip issue-tracker export.

1. Evidence timeline
   - For every Interactive Test Flow step, capture: url, title/text signal, screenshot, screen_recording or jam_url, console_errors, network_failures, and DOM/API assertion.
   - Store those fields in the step payload before calling autoqa_write_html_report.

2. Test data
   - Call list_test_data(field_type, name) for forms and generate valid, invalid, boundary, i18n/RTL, long, empty, duplicate, and malicious-but-safe inputs.
   - Use test_forms/fuzz_forms for non-destructive validation checks.

3. Accessibility power mode
   - Run a11y_audit(url) and keyboard_walk(url).
   - Check labels, contrast, focus order, focus traps, alt text, empty controls, duplicate IDs, zoom blocking, and keyboard-only completion.

4. API flow mapping
   - Run map_api(url, interact=true) or deep_test(url, include_api_map=true).
   - Tie API calls to UI steps: request URL, method, status, payload shape, auth pattern, response errors, and GraphQL/WebSocket findings.

5. Smart auth
   - Start with auth_status(url).
   - Prefer Chrome DevTools MCP/default Chrome session. If MFA/CAPTCHA/passkey appears, pause for the user, then continue.
   - Save reusable sessions with save_session and record auth state in the report.

6. Optional orchestration
   - If the host app uses LangGraph or similar, model the run as planner -> browser actor -> evidence collector -> specialist reviewers -> report writer.
   - Keep Fagun tool calls as the source of truth and include the orchestrator name in the report source.

7. Finish
   - Call autoqa_write_html_report.
   - Confirm run memory was created.
   - Use autoqa_compare_runs for before/after regression when a prior run exists.
"""


def infer_project_name(target_url: str = "", explicit: str = "") -> str:
    """Return a human report title from an explicit name or target hostname."""
    if explicit.strip():
        return explicit.strip()
    host = urlparse(target_url).netloc or urlparse("https://" + target_url).netloc
    host = host.split("@")[-1].split(":")[0]
    if not host:
        return "Fagun Project"
    parts = [p for p in host.replace("www.", "").split(".") if p]
    core = parts[0] if parts else host
    return core.replace("-", " ").replace("_", " ").title()


def default_report_path(project_name: str, target_url: str = "") -> str:
    """Return a deterministic-ish local report path for an AutoQA run."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    base = project_name or infer_project_name(target_url)
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "fagun"
    return str(Path("reports") / f"{slug}-autoqa-{stamp}.html")


def default_memory_dir(report_path: str = "") -> Path:
    """Return the local directory used for structured AutoQA run memory."""
    if report_path:
        return Path(report_path).resolve().parent / "runs"
    return Path("reports") / "runs"


def _slug(text: str, fallback: str = "fagun") -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or fallback


def _coerce_payload(result_json_or_text: str) -> dict[str, Any]:
    text = (result_json_or_text or "").strip()
    if not text:
        return {"verdict": "Unknown", "summary": "No result payload was provided.", "steps": [], "findings": []}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
        return {"verdict": "Unknown", "summary": payload, "steps": [], "findings": []}
    except Exception:
        return {"verdict": "Unknown", "summary": text, "steps": [], "findings": []}


def _finding_key(finding: Any) -> str:
    if isinstance(finding, dict):
        title = finding.get("type") or finding.get("label") or finding.get("name") or finding.get("detail") or finding.get("description")
        severity = finding.get("severity") or finding.get("status") or ""
        return f"{title}|{severity}".lower()
    return str(finding).lower()


def _run_record(
    project_name: str,
    target_url: str,
    goal: str,
    payload: dict[str, Any],
    report_path: str,
    source: str,
    generated: str | None = None,
) -> dict[str, Any]:
    """Create a structured run-memory record from an AutoQA payload."""
    generated = generated or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    project = infer_project_name(target_url, project_name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    run_id = f"{stamp}-{_slug(project)}"
    steps = _listify(payload.get("steps") or payload.get("action_trace") or payload.get("test_steps"))
    findings = _listify(payload.get("findings") or payload.get("bugs") or payload.get("issues"))
    evidence = _listify(payload.get("evidence") or payload.get("screenshots"))
    return {
        "schema_version": 1,
        "run_id": run_id,
        "project_name": project,
        "target_url": target_url,
        "goal": goal,
        "verdict": str(payload.get("verdict") or payload.get("status") or "Unknown"),
        "source": source or "fagun",
        "generated_at": generated,
        "report_path": str(report_path),
        "summary": payload.get("summary") or payload.get("executive_summary") or "",
        "steps": steps,
        "findings": findings,
        "evidence": evidence,
        "recommendations": _listify(payload.get("recommendations") or payload.get("fixes")),
        "mcp_usage": payload.get("mcp_usage") or payload.get("tools_used") or [],
        "raw_payload": payload,
    }


def save_run_memory(record: dict[str, Any], memory_dir: str | Path = "") -> str:
    """Persist a structured run record and update the local run-memory index."""
    base = Path(memory_dir) if memory_dir else default_memory_dir(str(record.get("report_path") or ""))
    base.mkdir(parents=True, exist_ok=True)
    run_id = str(record.get("run_id") or f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-fagun")
    record_path = base / f"{_slug(run_id)}.json"
    record["memory_path"] = str(record_path)
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    index_path = base / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        if not isinstance(index, list):
            index = []
    except Exception:
        index = []
    summary = {
        "run_id": run_id,
        "project_name": record.get("project_name"),
        "target_url": record.get("target_url"),
        "goal": record.get("goal"),
        "verdict": record.get("verdict"),
        "generated_at": record.get("generated_at"),
        "report_path": record.get("report_path"),
        "memory_path": str(record_path),
        "findings": len(_listify(record.get("findings"))),
        "steps": len(_listify(record.get("steps"))),
    }
    index = [item for item in index if not isinstance(item, dict) or item.get("run_id") != run_id]
    index.insert(0, summary)
    index_path.write_text(json.dumps(index[:200], indent=2, default=str), encoding="utf-8")
    return str(record_path)


def _load_index(memory_dir: str | Path = "") -> list[dict[str, Any]]:
    base = Path(memory_dir) if memory_dir else default_memory_dir()
    index_path = base / "index.json"
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def list_run_memory(limit: int = 10, memory_dir: str = "") -> str:
    """Return recent structured Fagun runs as JSON."""
    runs = _load_index(memory_dir)[: max(1, min(int(limit or 10), 100))]
    return json.dumps({"runs": runs}, indent=2, default=str)


def _load_run(ref: str, memory_dir: str | Path = "") -> dict[str, Any]:
    """Load a run by JSON path, run id, or report path."""
    candidates: list[Path] = []
    if ref:
        path = Path(ref)
        if path.exists():
            candidates.append(path)
        base = Path(memory_dir) if memory_dir else default_memory_dir()
        candidates.append(base / f"{_slug(ref)}.json")
        for item in _load_index(memory_dir):
            if ref in {str(item.get("run_id")), str(item.get("report_path")), str(item.get("memory_path"))}:
                candidates.append(Path(str(item.get("memory_path"))))
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    raise FileNotFoundError(f"Fagun run memory not found: {ref}")


def replay_prompt(run_ref: str, memory_dir: str = "") -> str:
    """Build a deterministic replay/regression prompt from a stored run."""
    run = _load_run(run_ref, memory_dir)
    steps = _listify(run.get("steps"))
    step_lines = []
    for i, step in enumerate(steps, 1):
        if isinstance(step, dict):
            label = step.get("label") or step.get("name") or step.get("action") or f"Step {i}"
            target = step.get("target") or step.get("url") or step.get("detail") or ""
            expected = step.get("expected") or step.get("status") or step.get("result") or ""
            step_lines.append(f"{i}. {label} — {target} — expected: {expected}".strip())
        else:
            step_lines.append(f"{i}. {step}")
    return (
        "Replay this Fagun run as a regression check.\n\n"
        f"Run ID: {run.get('run_id')}\n"
        f"Project: {run.get('project_name')}\n"
        f"Target: {run.get('target_url')}\n"
        f"Original prompt: {run.get('goal')}\n"
        f"Original verdict: {run.get('verdict')}\n\n"
        "Replay steps:\n"
        + ("\n".join(step_lines) if step_lines else "No structured steps were stored; inspect the original report and reconstruct the journey.")
        + "\n\nCompare the new run against the stored run. Mark fixed bugs, still-open bugs, new bugs, changed console/network failures, changed screenshots/recordings, and changed verdict. Generate a new Fagun HTML report and store run memory."
    )


def compare_runs(before_ref: str, after_ref: str, memory_dir: str = "") -> str:
    """Compare two stored Fagun runs and return a compact Markdown diff."""
    before = _load_run(before_ref, memory_dir)
    after = _load_run(after_ref, memory_dir)
    before_findings = {_finding_key(item): item for item in _listify(before.get("findings"))}
    after_findings = {_finding_key(item): item for item in _listify(after.get("findings"))}
    fixed = [before_findings[key] for key in before_findings.keys() - after_findings.keys()]
    new = [after_findings[key] for key in after_findings.keys() - before_findings.keys()]
    still = [after_findings[key] for key in after_findings.keys() & before_findings.keys()]

    def title(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("type") or item.get("label") or item.get("name") or item.get("detail") or "Finding")
        return str(item)

    lines = [
        "# Fagun Report Comparison",
        "",
        f"Before: {before.get('run_id')} — {before.get('verdict')} — {before.get('target_url')}",
        f"After: {after.get('run_id')} — {after.get('verdict')} — {after.get('target_url')}",
        "",
        "## Summary",
        f"- Steps: {len(_listify(before.get('steps')))} → {len(_listify(after.get('steps')))}",
        f"- Findings: {len(before_findings)} → {len(after_findings)}",
        f"- Fixed: {len(fixed)}",
        f"- Still Open: {len(still)}",
        f"- New: {len(new)}",
        "",
        "## Fixed Findings",
        *(f"- {title(item)}" for item in fixed),
        *(["- None"] if not fixed else []),
        "",
        "## Still Open",
        *(f"- {title(item)}" for item in still),
        *(["- None"] if not still else []),
        "",
        "## New Findings",
        *(f"- {title(item)}" for item in new),
        *(["- None"] if not new else []),
        "",
        "## Reports",
        f"- Before: {before.get('report_path')}",
        f"- After: {after.get('report_path')}",
    ]
    return "\n".join(lines)


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _site_origin(target_url: str) -> str:
    parsed = urlparse(target_url if "://" in target_url else "https://" + target_url)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _site_name(target_url: str) -> str:
    return infer_project_name(target_url)


def _node_type(text: str) -> str:
    hay = text.lower()
    if any(x in hay for x in ("signup", "sign up", "create account", "register")):
        return "signup"
    if any(x in hay for x in ("signin", "sign in", "login", "log in")):
        return "signin"
    if any(x in hay for x in ("assert", "verify", "check", "expect")):
        return "assert"
    if any(x in hay for x in ("screenshot", "evidence")):
        return "evidence"
    if any(x in hay for x in ("bug", "finding", "missing", "error", "fail")):
        return "finding"
    if any(x in hay for x in ("open", "navigate", "load", "visit")):
        return "open"
    return "step"


def _copy_evidence_fields(node: dict[str, Any], item: dict[str, Any]) -> None:
    """Copy optional per-step/per-bug evidence fields into a flow node."""
    for key in (
        "screenshot",
        "screenshots",
        "jam_url",
        "jam_report",
        "jam_link",
        "jam_screenshot",
        "recording",
        "screen_recording",
        "jam_recording",
        "evidence",
        "console",
        "console_errors",
        "network",
        "network_failures",
        "request",
        "status",
    ):
        value = item.get(key)
        if value:
            node[key] = value


def _flow_nodes(project: str, target_url: str, steps: list[Any], findings: list[Any], evidence: list[Any], logo_url: str = "") -> list[dict[str, Any]]:
    origin = _site_origin(target_url)
    nodes: list[dict[str, Any]] = [{
        "id": "site",
        "type": "site",
        "title": f"Opened {_site_name(target_url)}",
        "detail": f"Target website opened from {target_url or 'not provided'}.",
        "url": target_url,
        "icon": logo_url or (f"{origin}/favicon.ico" if origin else ""),
    }]
    for i, step in enumerate(steps, 1):
        if isinstance(step, dict):
            title = str(step.get("label") or step.get("name") or step.get("action") or f"Step {i}")
            detail = str(step.get("detail") or step.get("description") or step.get("result") or step.get("target") or "")
            node_type = str(step.get("node_type") or _node_type(f"{title} {detail}"))
            node = {
                "id": f"step-{i}",
                "type": node_type,
                "title": title,
                "detail": detail,
                "url": step.get("url") or "",
                "status": step.get("status") or step.get("verdict") or "",
            }
            _copy_evidence_fields(node, step)
        else:
            title = str(step)
            node = {"id": f"step-{i}", "type": _node_type(title), "title": title, "detail": title}
        nodes.append(node)
    for i, finding in enumerate(findings, 1):
        if isinstance(finding, dict):
            title = str(finding.get("type") or finding.get("label") or f"Finding {i}")
            detail = str(finding.get("detail") or finding.get("description") or finding.get("evidence") or "")
            severity = str(finding.get("severity") or "")
        else:
            title = f"Finding {i}"
            detail = str(finding)
            severity = ""
        node = {
            "id": f"finding-{i}",
            "type": "finding",
            "title": title,
            "detail": detail,
            "status": severity,
            "jira_html": _jira_ticket_html(finding, target_url, i),
        }
        if isinstance(finding, dict):
            _copy_evidence_fields(node, finding)
        nodes.append(node)
    if evidence:
        nodes.append({
            "id": "evidence",
            "type": "evidence",
            "title": "Evidence collected",
            "detail": f"{len(evidence)} evidence item(s), including screenshots, console, network, or DOM assertions.",
        })
    if len(nodes) == 1:
        nodes.append({"id": "summary", "type": "step", "title": f"{project} test summary", "detail": "No individual steps were supplied."})
    return nodes


def _finding_text(finding: Any, *keys: str, default: str = "") -> str:
    if isinstance(finding, dict):
        for key in keys:
            value = finding.get(key)
            if value:
                return str(value)
    return str(finding) if finding is not None and not isinstance(finding, dict) else default


def _jira_ticket_html(finding: Any, target_url: str, i: int) -> str:
        typ = _finding_text(finding, "type", "label", "name", default=f"Finding {i}")
        detail = _finding_text(finding, "detail", "description", "evidence", default="No detail supplied.")
        severity_raw = _finding_text(finding, "severity", default="low").lower()
        severity = {"high": "Critical", "medium": "Major", "low": "Minor"}.get(severity_raw, severity_raw.title() or "Minor")
        priority = {"high": "Highest", "medium": "High", "low": "Medium"}.get(severity_raw, "Medium")
        evidence = _finding_text(finding, "evidence", "screenshot", "request", default="See Fagun evidence and screenshots in this report.")
        jam = _finding_text(finding, "jam_url", "jam_report", "jam_link", default="")
        recording = _finding_text(finding, "screen_recording", "recording", "jam_recording", default="")
        jam_screenshot = _finding_text(finding, "jam_screenshot", default="")
        request = _finding_text(finding, "request", "network_request", default="Not captured / not applicable.")
        method = _finding_text(finding, "method", "http_method", default="Not captured / not applicable.")
        status = _finding_text(finding, "status", "network_status", default="Not captured / not applicable.")
        payload = _finding_text(finding, "payload", "request_payload", default="{}")
        response = _finding_text(finding, "response", "network_response", default="{}")
        screenshot = _finding_text(finding, "screenshot", default=jam_screenshot or evidence)
        labels = finding.get("labels") if isinstance(finding, dict) else None
        if not isinstance(labels, list) or not labels:
            labels = ["frontend", "qa"]
            hay = f"{typ} {detail}".lower()
            if any(x in hay for x in ("api", "request", "status", "response", "server")):
                labels.append("api")
            if any(x in hay for x in ("security", "csp", "hsts", "xss", "header")):
                labels.append("security")
            if any(x in hay for x in ("performance", "slow", "vitals", "lcp", "cls")):
                labels.append("performance")
            if any(x in hay for x in ("ui", "ux", "visual", "button", "layout")):
                labels.extend(["ui", "ux"])
        labels = list(dict.fromkeys(str(label) for label in labels))
        module = _finding_text(finding, "module", "area", default=typ.split()[0] if typ else "Fagun")
        expected = _finding_text(
            finding,
            "expected",
            default="The tested flow should complete without errors, security gaps, accessibility blockers, or user confusion.",
        )
        fix = _finding_text(
            finding,
            "fix",
            "recommendation",
            default="Fix the root cause, add a regression check, and rerun the same Fagun scenario.",
        )
        summary = f"{typ} on {target_url or 'target'}"
        steps = finding.get("steps") if isinstance(finding, dict) else None
        if not isinstance(steps, list) or not steps:
            steps = [
                f"Open {target_url or 'the target URL'}.",
                "Run the Fagun scenario described in the user prompt.",
                f"Observe: {detail}",
            ]
        preconditions = finding.get("preconditions") if isinstance(finding, dict) else None
        if not isinstance(preconditions, list) or not preconditions:
            preconditions = ["Target is reachable.", "Tester is authorized to test this environment."]
        steps_html = "".join(f"<li>{escape(str(step))}</li>" for step in steps)
        preconditions_html = "".join(f"<li>{escape(str(item))}</li>" for item in preconditions)
        labels_html = "\n".join(escape(str(label)) for label in labels)
        evidence_items = [item for item in (screenshot, jam_screenshot, jam, recording, evidence) if item]
        evidence_html = "".join(f"<li>{escape(str(item))}</li>" for item in dict.fromkeys(evidence_items))
        return f"""
        <article class="jira-ticket">
          <div class="ticket-head">
            <span class="ticket-key">FAGUN-{i}</span>
            <span class="ticket-priority">{escape(priority)}</span>
          </div>
          <h3>🐞 Jira Bug Report</h3>
          <div class="ticket-section"><h4>Title</h4><pre>[{escape(module)}] {escape(typ)}</pre><p class="muted">Example title generated from Fagun evidence.</p></div>
          <div class="ticket-section"><h4>Bug Summary</h4><p>{escape(detail)}</p></div>
          <div class="ticket-section"><h4>Environment</h4><ul><li><b>Environment:</b> Test target / STG unless otherwise specified</li><li><b>Platform:</b> Web</li><li><b>Browser:</b> Chrome DevTools MCP / default Chrome unless fallback was recorded</li><li><b>OS:</b> Local tester machine</li><li><b>Build Version:</b> Not provided by target</li></ul></div>
          <div class="ticket-section"><h4>Preconditions</h4><ul>{preconditions_html}</ul></div>
          <div class="ticket-section"><h4>Steps to Reproduce</h4><ol>{steps_html}</ol></div>
          <div class="ticket-section"><h4>Actual Result</h4><p>{escape(detail)}</p></div>
          <div class="ticket-section"><h4>Expected Result</h4><p>{escape(expected)}</p></div>
          <div class="ticket-section"><h4>API Information (If Applicable)</h4><div class="api-grid"><div><div class="detail-label">Request URL</div><pre>{escape(request)}</pre></div><div><div class="detail-label">Method</div><pre>{escape(method)}</pre></div><div><div class="detail-label">Status Code</div><pre>{escape(status)}</pre></div></div></div>
          <div class="ticket-section"><h4>Request Payload (Optional)</h4><pre>{escape(payload)}</pre></div>
          <div class="ticket-section"><h4>Response (Optional)</h4><pre>{escape(response)}</pre></div>
          <div class="ticket-section"><h4>Evidence</h4><ul>{evidence_html}</ul></div>
          <div class="ticket-section"><h4>Impact</h4><ul><li>{escape('User cannot complete the workflow.' if severity_raw in {'high','medium'} else 'Issue can reduce product quality or user confidence.')}</li><li>{escape('Feature becomes unusable or less trustworthy depending on affected flow.' if severity_raw in {'high','medium'} else 'Hardening/polish improvement recommended.')}</li></ul></div>
          <div class="ticket-grid">
            <div><div class="detail-label">Severity</div><div class="detail-value">{escape(severity)} ({escape({'high':'P1','medium':'P2','low':'P3'}.get(severity_raw, 'P3'))})</div></div>
            <div><div class="detail-label">Priority</div><div class="detail-value">{escape(priority)}</div></div>
            <div><div class="detail-label">Frequency</div><div class="detail-value">Always (100%)</div></div>
          </div>
          <div class="ticket-section"><h4>Labels</h4><pre>{labels_html}</pre></div>
          <div class="ticket-section"><h4>Assignee</h4><pre>Developer Name</pre></div>
          <div class="ticket-section"><h4>QA Notes</h4><ul><li><b>Reproducible:</b> Yes</li><li><b>Regression:</b> Unknown</li><li><b>Blocking:</b> {escape('Yes' if severity_raw in {'high'} else 'No')}</li><li><b>Related Ticket(s):</b> DS-XXX</li><li><b>Suggested Fix:</b> {escape(fix)}</li></ul></div>
        </article>
        """


def _findings_summary_section(findings: list[Any]) -> str:
    items = []
    for finding in findings:
        if isinstance(finding, dict):
            title = finding.get("type") or finding.get("label") or finding.get("name") or "Finding"
            detail = finding.get("detail") or finding.get("description") or finding.get("evidence") or ""
            status = finding.get("status") or finding.get("severity") or ""
            detail_html = f" — {escape(str(detail))}" if detail else ""
            status_html = f'<div class="muted">{escape(str(status))}</div>' if status else ""
            items.append(
                f"<li><b>{escape(str(title))}</b>"
                f"{detail_html}"
                f"{status_html}</li>"
            )
        else:
            items.append(f"<li>{escape(str(finding))}</li>")
    body = "".join(items) if items else "<li>No findings were supplied.</li>"
    return (
        "<section><h2>Findings / Bugs</h2>"
        '<p class="muted">Click each finding node in the Interactive Test Flow to view its full Jira bug ticket on the right side.</p>'
        f"<ul>{body}</ul></section>"
    )


def build_html_report(
    project_name: str,
    target_url: str,
    goal: str,
    result_json_or_text: str,
    source: str = "fagun",
) -> str:
    """Build a standalone branded HTML report for a plain-English Fagun run."""
    project = infer_project_name(target_url, project_name)
    payload = _coerce_payload(result_json_or_text)
    verdict = str(payload.get("verdict") or payload.get("status") or "Unknown")
    summary = payload.get("summary") or payload.get("executive_summary") or ""
    steps = _listify(payload.get("steps") or payload.get("action_trace") or payload.get("test_steps"))
    findings = _listify(payload.get("findings") or payload.get("bugs") or payload.get("issues"))
    evidence = _listify(payload.get("evidence") or payload.get("screenshots"))
    recommendations = _listify(payload.get("recommendations") or payload.get("fixes"))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    tool_title = "Fagun Tools"
    source_label = source or "fagun"
    verdict_class = "pass" if verdict.lower() in {"pass", "passed", "success"} else "fail" if "fail" in verdict.lower() else "warn"
    origin = _site_origin(target_url)
    site_name = _site_name(target_url)
    favicon = f"{origin}/favicon.ico" if origin else ""
    logo_url = str(payload.get("website_logo") or payload.get("site_logo") or payload.get("favicon") or favicon)
    logo_initial = escape((site_name[:1] or "F").upper())
    logo_img = (
        f'<img src="{escape(logo_url)}" alt="{escape(site_name)} logo" '
        "onerror=\"this.style.display='none';this.nextElementSibling.style.display='grid'\">"
        if logo_url
        else ""
    )
    logo_fallback_style = "display:none" if logo_url else "display:grid"
    site_logo_html = (
        f'<span class="site-logo">{logo_img}'
        f'<span class="site-logo-fallback" style="{logo_fallback_style}">{logo_initial}</span></span>'
    )
    nodes = _flow_nodes(project, target_url, steps, findings, evidence, logo_url=logo_url)
    nodes_json = json.dumps(nodes, default=str)

    def render_item(item: Any) -> str:
        if isinstance(item, dict):
            title = item.get("label") or item.get("name") or item.get("type") or item.get("action") or "Item"
            detail = item.get("detail") or item.get("description") or item.get("evidence") or item.get("result") or ""
            meta = " · ".join(str(item.get(k)) for k in ("url", "status", "screenshot") if item.get(k))
            detail_html = f" — {escape(str(detail))}" if detail else ""
            meta_html = f'<div class="muted">{escape(meta)}</div>' if meta else ""
            return (
                f"<li><b>{escape(str(title))}</b>"
                f"{detail_html}"
                f"{meta_html}</li>"
            )
        return f"<li>{escape(str(item))}</li>"

    def render_section(title: str, items: list[Any], empty: str) -> str:
        body = "".join(render_item(i) for i in items) if items else f"<li>{escape(empty)}</li>"
        return f"<section><h2>{escape(title)}</h2><ul>{body}</ul></section>"

    summary_html = (
        "".join(f"<p>{escape(str(s))}</p>" for s in summary)
        if isinstance(summary, list)
        else f"<p>{escape(str(summary or 'No summary provided.'))}</p>"
    )
    prompt_html = escape(goal or "Not provided")
    logo_svg = """<svg class="logo" viewBox="0 0 64 64" aria-label="Fagun logo" role="img">
      <path d="M6 8 L28 22 L36 22 L58 8 L52 32 L12 32 Z" fill="#E8B04B"/>
      <path d="M12 32 L32 54 L52 32 Z" fill="#d99f3c"/>
      <path d="M10 12 L26 23 L15 27 Z" fill="#1a1226"/>
      <path d="M54 12 L38 23 L49 27 Z" fill="#1a1226"/>
      <circle cx="24" cy="34" r="2.4" fill="#1a1226"/>
      <circle cx="40" cy="34" r="2.4" fill="#1a1226"/>
      <circle cx="24" cy="34" r="2.7" fill="#E8B04B" opacity=".75"/>
      <circle cx="40" cy="34" r="2.7" fill="#E8B04B" opacity=".75"/>
      <path d="M27 44 L32 49 L37 44 Z" fill="#1a1226"/>
    </svg>"""
    def _node_dot(n: dict) -> str:
        icon = str(n.get("icon") or "")
        if n.get("type") == "site" and icon:
            safe = escape(icon)
            return (
                f'<span class="dot">'
                f'<img src="{safe}" width="14" height="14" '
                f'style="border-radius:3px;object-fit:contain;display:block" '
                f"onerror=\"this.style.display='none'\">"
                f'</span>'
            )
        return '<span class="dot"></span>'

    node_cards = "\n".join(
        f"""<button class="node node-{escape(str(n.get("type", "step")))}" data-node="{i}">
          {_node_dot(n)}
          <span class="node-title">{escape(str(n.get("title", "Node")))}</span>
          <span class="node-type">{escape(str(n.get("type", "step")).upper())}</span>
        </button>"""
        for i, n in enumerate(nodes)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{escape(project)} - Fagun AutoQA Report</title>
  <style>
    :root {{ color-scheme:dark; --gold:#E8B04B; --gold-soft:#f0c877; --ink:#0d0b16; --ink2:#241a33; --text:#F3EEE6; --muted:#a79bb5; --line:rgba(243,238,230,.11); --card:rgba(255,255,255,.03); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:linear-gradient(180deg,#0d0b16 0%,#181026 55%,#241a33 100%); color:var(--text); min-height:100vh; }}
    a {{ color:var(--gold-soft); }}
    .wrap {{ max-width:1120px; margin:0 auto; padding:88px clamp(20px,5vw,44px) 56px; }}
    .topbar {{ position:fixed; top:0; left:0; right:0; z-index:50; backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); background:rgba(13,11,22,.86); border-bottom:1px solid var(--line); }}
    .topbar-inner {{ max-width:1120px; margin:0 auto; padding:14px clamp(20px,5vw,44px); display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    .topbar .logo {{ width:30px; height:30px; }}
    .nav {{ display:flex; align-items:center; gap:18px; font-size:14px; }}
    .nav a {{ color:var(--muted); text-decoration:none; }}
    .nav a:hover {{ color:var(--text); }}
    header {{ border:1px solid rgba(232,176,75,.2); background:linear-gradient(180deg,rgba(31,27,40,.95),rgba(13,10,22,.95)); border-radius:22px; padding:clamp(22px,4vw,34px); margin-bottom:22px; box-shadow:0 28px 90px -42px rgba(0,0,0,.95),inset 0 1px 0 rgba(255,255,255,.05); }}
    .brand {{ display:flex; align-items:center; gap:14px; margin-bottom:12px; }}
    .logo {{ width:54px; height:54px; flex:0 0 auto; }}
    .eyebrow, .pill {{ color:var(--gold); font-weight:600; text-transform:uppercase; font-size:12px; letter-spacing:.2em; }}
    h1,h2,h3 {{ font-family:Didot,'Bodoni MT','Playfair Display',Georgia,serif; font-weight:500; letter-spacing:-.01em; }}
    h1 {{ margin:4px 0 10px; font-size:clamp(2.2rem,5vw,4.4rem); line-height:1; }}
    h2 {{ margin:30px 0 12px; font-size:clamp(1.45rem,2.4vw,2.05rem); border-bottom:1px solid var(--line); padding-bottom:8px; }}
    .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; margin-top:16px; }}
    .card, section {{ border:1px solid var(--line); background:var(--card); border-radius:16px; padding:clamp(18px,3vw,26px); }}
    .k {{ color:var(--gold); font-size:12px; text-transform:uppercase; font-weight:600; letter-spacing:.08em; }}
    .v {{ margin-top:3px; word-break:break-word; }}
    .verdict {{ display:inline-block; padding:5px 10px; border-radius:999px; font-weight:800; }}
    .pass {{ background:rgba(74,222,128,.12); border:1px solid rgba(74,222,128,.35); color:#4ade80; }}
    .fail {{ background:rgba(248,113,113,.12); border:1px solid rgba(248,113,113,.35); color:#f87171; }}
    .warn {{ background:rgba(232,176,75,.12); border:1px solid rgba(232,176,75,.35); color:var(--gold-soft); }}
    ul {{ margin:0; padding-left:20px; }}
    li {{ margin:7px 0; }}
    .muted {{ color:var(--muted); font-size:13px; margin-top:2px; }}
    code {{ background:#08060f; color:var(--gold-soft); padding:2px 5px; border-radius:5px; }}
    .prompt {{ white-space:pre-wrap; background:#08060f; border:1px solid var(--line); border-radius:12px; padding:16px 18px; color:var(--text); font-family:'SF Mono','JetBrains Mono',Menlo,Consolas,monospace; font-size:13.5px; line-height:1.8; }}
    .site-opened {{ display:flex; align-items:center; gap:12px; }}
    .site-logo {{ width:38px; height:38px; flex:0 0 auto; border-radius:10px; overflow:hidden; border:1px solid rgba(232,176,75,.25); background:#fff; }}
    .site-logo img,.site-logo-fallback {{ width:100%; height:100%; object-fit:contain; }}
    .site-logo-fallback {{ place-items:center; background:rgba(232,176,75,.14); color:var(--gold); font-weight:800; }}
    .flow-grid {{ display:grid; grid-template-columns:minmax(260px,360px) 1fr; gap:16px; align-items:start; }}
    .flow {{ position:sticky; top:92px; display:flex; flex-direction:column; gap:12px; background:#050507; border:1px solid rgba(232,176,75,.2); border-radius:22px; padding:18px; overflow:visible; }}
    .flow:before {{ content:""; position:absolute; inset:0; background:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px); background-size:42px 42px; opacity:.42; pointer-events:none; }}
    .flow:after {{ content:""; position:absolute; left:36px; top:32px; bottom:32px; width:2px; background:linear-gradient(var(--gold),rgba(232,176,75,.15)); opacity:.75; }}
    .node {{ position:relative; z-index:1; display:grid; grid-template-columns:28px 1fr auto; gap:10px; align-items:center; width:100%; text-align:left; color:var(--text); background:linear-gradient(180deg,rgba(31,31,34,.96),rgba(18,18,20,.96)); border:1px solid rgba(255,255,255,.13); border-radius:10px; padding:13px 14px; cursor:pointer; box-shadow:0 18px 50px -34px rgba(0,0,0,.95),inset 0 1px 0 rgba(255,255,255,.05); }}
    .node:hover, .node.active {{ border-color:rgba(232,176,75,.55); box-shadow:0 0 34px -18px rgba(232,176,75,.85); }}
    .dot {{ width:18px; height:18px; border-radius:7px; display:inline-grid; place-items:center; background:rgba(232,176,75,.14); border:1px solid rgba(232,176,75,.36); box-shadow:0 0 0 5px #111; z-index:2; }}
    .node-site .dot {{ background:rgba(74,222,128,.18); border-color:rgba(74,222,128,.42); }}
    .node-signup .dot {{ background:rgba(232,176,75,.2); border-color:rgba(232,176,75,.55); }}
    .node-signin .dot {{ background:rgba(127,176,232,.18); border-color:rgba(127,176,232,.42); }}
    .node-assert .dot {{ background:rgba(240,200,119,.18); border-color:rgba(240,200,119,.42); }}
    .node-finding .dot {{ background:rgba(248,113,113,.18); border-color:rgba(248,113,113,.42); }}
    .node-evidence .dot {{ background:rgba(74,222,128,.18); border-color:rgba(74,222,128,.42); }}
    .node-title {{ font-weight:700; }}
    .node-type {{ font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:2px 8px; }}
    .detail-panel {{ min-height:260px; max-height:calc(100vh - 112px); overflow-y:auto; position:sticky; top:92px; scrollbar-color:var(--gold) #1b1624; }}
    .detail-panel h3 {{ margin:0 0 8px; font-size:20px; }}
    .detail-row {{ margin-top:10px; }}
    .detail-label {{ color:var(--gold); font-size:12px; text-transform:uppercase; font-weight:700; }}
    .detail-value {{ margin-top:2px; white-space:pre-wrap; word-break:break-word; }}
    .evidence-grid {{ display:grid; gap:12px; margin:12px 0 16px; }}
    .evidence-card {{ border:1px solid var(--line); border-radius:12px; background:#050507; padding:12px; }}
    .evidence-card a {{ display:inline-flex; margin-top:8px; color:var(--gold-soft); word-break:break-word; }}
    .evidence-media {{ width:100%; max-height:260px; object-fit:contain; border-radius:10px; border:1px solid var(--line); background:#08060f; }}
    .docs-links {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-top:14px; }}
    .docs-link {{ display:block; text-decoration:none; color:var(--text); border:1px solid var(--line); border-radius:14px; padding:14px 16px; background:var(--card); }}
    .docs-link:hover {{ border-color:rgba(232,176,75,.45); }}
    .jira-ticket {{ border:1px solid var(--line); background:#08060f; border-radius:16px; padding:18px; margin:14px 0; }}
    .ticket-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }}
    .ticket-key,.ticket-priority {{ display:inline-flex; align-items:center; border-radius:999px; padding:4px 10px; font-size:12px; font-weight:700; border:1px solid rgba(232,176,75,.35); color:var(--gold); background:rgba(232,176,75,.1); }}
    .ticket-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; margin:12px 0; }}
    .ticket-section {{ border-top:1px solid var(--line); padding-top:12px; margin-top:12px; }}
    .ticket-section h4 {{ margin:0 0 6px; color:var(--gold); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    .ticket-section p {{ margin:0; color:var(--text); }}
    .ticket-section pre {{ margin:0; white-space:pre-wrap; word-break:break-word; background:#050507; border:1px solid var(--line); border-radius:10px; padding:12px; color:var(--muted); }}
    @media (max-width: 820px) {{ .flow-grid {{ grid-template-columns:1fr; }} .flow,.detail-panel {{ position:static; max-height:none; overflow:visible; }} }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <a href="{FAGUN_HOME_URL}" style="display:flex;align-items:center;gap:11px;text-decoration:none;color:var(--text)">{logo_svg}<span style="font-family:Didot,Georgia,serif;font-size:21px;font-weight:600">Fagun</span><span class="muted">/ report</span></a>
      <nav class="nav">
        <a href="{FAGUN_HOME_URL}">Home</a>
        <a href="{FAGUN_DOCS_URL}">Docs</a>
        <a href="{FAGUN_GITHUB_URL}">GitHub</a>
        <a href="{FAGUN_PYPI_URL}">PyPI</a>
      </nav>
    </div>
  </div>
  <div class="wrap">
    <header>
      <div class="brand">{logo_svg}<div><div class="eyebrow">Fagun AutoQA HTML Report</div><h1>{escape(project)}</h1></div></div>
      <div class="verdict {verdict_class}">{escape(verdict)}</div>
      <div class="meta">
        <div class="card"><div class="k">Project Name</div><div class="v">{escape(project)}</div></div>
        <div class="card"><div class="k">Collected From</div><div class="v">{escape(target_url or 'Not provided')}</div></div>
        <div class="card"><div class="k">Opened Website</div><div class="v site-opened">{site_logo_html}<span>{escape(site_name)}<br><span class="muted">{escape(target_url or "Not provided")}</span></span></div></div>
        <div class="card"><div class="k">Generated</div><div class="v">{escape(generated)}</div></div>
        <div class="card"><div class="k">Runner Source</div><div class="v">{escape(source_label)}</div></div>
        <div class="card"><div class="k">Tooling</div><div class="v">{tool_title}: Chrome DevTools MCP/default Chrome first, Jam MCP evidence when available, Fagun browser fallback only if needed, screenshots, console, network, DOM assertions, HTML report.</div></div>
      </div>
    </header>
    <section><h2>User Full Prompt</h2><div class="prompt">{prompt_html}</div></section>
    <section>
      <h2>Fagun Pages</h2>
      <p class="muted">Quick links included in every report so users can return to the main Fagun site, documentation, source, and package page.</p>
      <div class="docs-links">
        <a class="docs-link" href="{FAGUN_HOME_URL}"><span class="pill">Home</span><br>Fagun product overview</a>
        <a class="docs-link" href="{FAGUN_DOCS_URL}"><span class="pill">Docs</span><br>Full documentation and workflow</a>
        <a class="docs-link" href="{FAGUN_GITHUB_URL}"><span class="pill">GitHub</span><br>Source code and issues</a>
        <a class="docs-link" href="{FAGUN_PYPI_URL}"><span class="pill">PyPI</span><br>Installable package</a>
      </div>
    </section>
    <section>
      <h2>Interactive Test Flow</h2>
      <div class="flow-grid">
        <div class="flow">{node_cards}</div>
        <div class="card detail-panel" id="detailPanel">
          <h3>Select a node</h3>
          <div class="muted">Click any node to inspect what Fagun did, what page/action it touched, and what evidence was collected.</div>
        </div>
      </div>
    </section>
  </div>
  <script>
    const nodes = {nodes_json};
    const buttons = [...document.querySelectorAll('.node')];
    const panel = document.getElementById('detailPanel');
    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function firstValue(...values) {{
      return values.find(value => value && String(value).trim());
    }}
    function isImage(value) {{
      return /\\.(png|jpe?g|gif|webp|svg)(\\?|#|$)/i.test(String(value || ''));
    }}
    function isVideo(value) {{
      return /\\.(mp4|webm|mov|m4v)(\\?|#|$)/i.test(String(value || ''));
    }}
    function evidenceCard(label, value, kind='link') {{
      if (!value) return '';
      const safe = esc(value);
      let media = '';
      if (kind === 'image' && isImage(value)) {{
        media = `<img class="evidence-media" src="${{safe}}" alt="${{esc(label)}}">`;
      }} else if (kind === 'video' && isVideo(value)) {{
        media = `<video class="evidence-media" src="${{safe}}" controls></video>`;
      }}
      const href = /^(https?:|file:|\\/)/.test(String(value)) ? safe : '';
      return `<div class="evidence-card"><div class="detail-label">${{esc(label)}}</div>${{media}}${{href ? `<a href="${{href}}" target="_blank" rel="noreferrer">${{safe}}</a>` : `<div class="detail-value">${{safe}}</div>`}}</div>`;
    }}
    function renderEvidenceBlock(node) {{
      const jam = firstValue(node.jam_url, node.jam_report, node.jam_link);
      const recording = firstValue(node.screen_recording, node.recording, node.jam_recording);
      const screenshot = firstValue(node.jam_screenshot, node.screenshot, node.screenshots);
      const cards = [
        evidenceCard('Jam report', jam),
        evidenceCard('Screen recording', recording, 'video'),
        evidenceCard('Screenshot', screenshot, 'image')
      ].join('');
      return cards ? `<div class="evidence-grid">${{cards}}</div>` : '';
    }}
    function showNode(index) {{
      const node = nodes[index];
      buttons.forEach(b => b.classList.remove('active'));
      if (buttons[index]) buttons[index].classList.add('active');
      if (node.jira_html) {{
        panel.innerHTML = renderEvidenceBlock(node) + node.jira_html;
        return;
      }}
      const evidenceBlock = renderEvidenceBlock(node);
      const rows = [
        ['Type', node.type],
        ['Status', node.status],
        ['URL', node.url],
        ['Jam report', firstValue(node.jam_url, node.jam_report, node.jam_link)],
        ['Screen recording', firstValue(node.screen_recording, node.recording, node.jam_recording)],
        ['Screenshot', firstValue(node.jam_screenshot, node.screenshot, node.screenshots)],
        ['Console', node.console_errors || node.console],
        ['Network', node.network_failures || node.network || node.request],
        ['Evidence', node.evidence],
        ['Details', node.detail],
      ].filter(row => row[1]);
      panel.innerHTML = `<h3>${{esc(node.title)}}</h3>` + evidenceBlock + rows.map(row =>
        `<div class="detail-row"><div class="detail-label">${{esc(row[0])}}</div><div class="detail-value">${{esc(row[1])}}</div></div>`
      ).join('');
    }}
    buttons.forEach((button, index) => button.addEventListener('click', () => showNode(index)));
    if (buttons.length) showNode(0);
  </script>
</body>
</html>
"""


def write_html_report(
    project_name: str,
    target_url: str,
    goal: str,
    result_json_or_text: str,
    report_path: str = "",
    source: str = "fagun",
    memory_dir: str = "",
) -> str:
    """Write the AutoQA HTML report and return the path."""
    project = infer_project_name(target_url, project_name)
    payload = _coerce_payload(result_json_or_text)
    path = Path(report_path or default_report_path(project, target_url))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_html_report(project, target_url, goal, result_json_or_text, source=source),
        encoding="utf-8",
    )
    record = _run_record(project, target_url, goal, payload, str(path), source)
    save_run_memory(record, memory_dir or default_memory_dir(str(path)))
    return str(path)
