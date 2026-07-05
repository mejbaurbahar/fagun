"""Fagun response style layer.

This module gives any MCP client a stable "Fagun style" contract:
- a model-agnostic prompt to paste into system/custom instructions,
- a JSON schema that wrappers/frontends can render as cards,
- a Markdown renderer for plain AI chat surfaces.
"""

from __future__ import annotations

import json
from typing import Any


STYLE_SECTIONS = [
    ("summary", "Executive Summary", "What matters most, in 1-3 short bullets."),
    ("problem", "Problem", "The issue, request, or goal being handled."),
    ("analysis", "Analysis", "Relevant findings, constraints, evidence, and reasoning summary."),
    ("solution", "Solution", "The recommended fix or implementation path."),
    ("implementation", "Implementation", "Files, commands, code, or concrete actions taken."),
    ("test_cases", "Test Cases", "Positive, negative, regression, edge, and automation tests."),
    ("edge_cases", "Edge Cases", "Boundary states, unusual users, devices, data, and failure modes."),
    ("risks", "Risks", "Security, reliability, UX, performance, or delivery risk."),
    ("production_impact", "Production Impact", "User/business impact and release decision."),
    ("api_validation", "API Validation", "Request/response, auth, error, idempotency, and contract checks."),
    ("performance", "Performance", "Speed, Core Web Vitals, resource, and scalability considerations."),
    ("final_recommendation", "Final Recommendation", "Clear next action."),
]

STYLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "solution", "final_recommendation"],
    "properties": {
        "summary": {"type": "array", "items": {"type": "string"}},
        "problem": {"type": "string"},
        "analysis": {"type": "array", "items": {"type": "string"}},
        "solution": {"type": "array", "items": {"type": "string"}},
        "implementation": {"type": "array", "items": {"type": "string"}},
        "test_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "expected": {"type": "string"},
                },
            },
        },
        "edge_cases": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "production_impact": {"type": "string"},
        "api_validation": {"type": "array", "items": {"type": "string"}},
        "performance": {"type": "array", "items": {"type": "string"}},
        "jira_ticket": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {"type": "string"},
                "description": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            },
        },
        "final_recommendation": {"type": "string"},
    },
}


def style_prompt(mode: str = "markdown") -> str:
    """Return the reusable instruction block for any AI model/client."""
    mode = (mode or "markdown").strip().lower()
    schema_note = ""
    if mode in {"json", "schema", "structured"}:
        schema_note = (
            "\nReturn valid JSON matching the Fagun response schema. "
            "Do not wrap JSON in Markdown fences unless the client explicitly asks."
        )
    return (
        "You are Fagun AI. Format every answer in Fagun Style.\n\n"
        "Rules:\n"
        "- Be concise, decisive, and evidence-based.\n"
        "- Use the same section order every time.\n"
        "- Skip a section only when it truly does not apply.\n"
        "- Prefer bullets over long paragraphs.\n"
        "- Include test cases, risks, edge cases, production impact, API validation, "
        "and performance considerations whenever useful.\n"
        "- For QA/security findings, include severity, reproduction, observed, expected, "
        "impact, and fix.\n"
        "- For code tasks, include changed files, verification commands, and residual risk.\n"
        "- Keep chat output compact; put large evidence into files/reports.\n"
        f"{schema_note}\n\n"
        "Fagun Style section order:\n"
        "1. Executive Summary\n"
        "2. Problem\n"
        "3. Analysis\n"
        "4. Solution\n"
        "5. Implementation\n"
        "6. Test Cases\n"
        "7. Edge Cases\n"
        "8. Risks\n"
        "9. Production Impact\n"
        "10. API Validation\n"
        "11. Performance\n"
        "12. Jira Ticket, only for bugs/tasks\n"
        "13. Final Recommendation"
    )


def schema_json() -> str:
    return json.dumps(STYLE_SCHEMA, indent=2)


def _list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _render_items(items: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            if {"name", "expected"} & set(item):
                name = item.get("name", "case")
                kind = item.get("type", "test")
                expected = item.get("expected", "")
                lines.append(f"- `{kind}` {name}: {expected}".rstrip())
            else:
                compact = ", ".join(f"{k}: {v}" for k, v in item.items() if v not in (None, "", []))
                lines.append(f"- {compact}")
        else:
            lines.append(f"- {item}")
    return lines


def render_response(payload: dict[str, Any], title: str = "Fagun Response") -> str:
    """Render a structured response dict into Fagun-style Markdown."""
    lines = [f"# {title}", ""]
    for key, label, _help in STYLE_SECTIONS:
        value = payload.get(key)
        items = _list(value)
        if not items:
            continue
        lines += [f"## {label}", ""]
        if key == "problem" or key in {"production_impact", "final_recommendation"}:
            lines.append(str(items[0]))
        else:
            lines.extend(_render_items(items))
        lines.append("")

    jira = payload.get("jira_ticket")
    if isinstance(jira, dict) and any(jira.values()):
        lines += ["## Jira Ticket", ""]
        if jira.get("title"):
            lines.append(f"**Title:** {jira['title']}")
        if jira.get("priority"):
            lines.append(f"**Priority:** {jira['priority']}")
        if jira.get("description"):
            lines.append(f"**Description:** {jira['description']}")
        ac = _list(jira.get("acceptance_criteria"))
        if ac:
            lines.append("**Acceptance Criteria:**")
            lines.extend(f"- {x}" for x in ac)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def coerce_payload(text_or_json: str, title: str = "Fagun Response") -> dict[str, Any]:
    """Convert JSON or plain text into the structured response shape."""
    try:
        parsed = json.loads(text_or_json)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {
        "summary": [text_or_json.strip()],
        "problem": "",
        "solution": [],
        "final_recommendation": "Review the summary above and ask Fagun for a deeper structured pass if needed.",
        "_title": title,
    }
