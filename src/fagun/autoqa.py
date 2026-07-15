"""Model-agnostic AutoQA workflow guidance.

Fagun does not call an LLM provider directly. The host AI client plans the test
with its own model, then uses Fagun MCP tools to execute browser actions. That
keeps Fagun usable from Claude, Codex, Antigravity, Cursor, Windsurf, and local
models without asking the end user for Groq/OpenAI/Anthropic/Gemini API keys.
"""

from __future__ import annotations

import json


AUTOQA_WORKFLOW = """You are running AutoQA through Fagun.

Operating rule:
- Do not ask the user for Groq, OpenAI, Anthropic, Gemini, or other model API keys.
- Use the current AI client/model to reason and plan.
- Use Fagun MCP browser tools to collect evidence from the live site.
- Only test public or explicitly authorized targets.
- Never perform destructive actions or submit real payments/orders unless the user explicitly confirms a safe test environment.

Workflow:
1. Restate the target URL, objective, assumptions, and safety constraints.
2. Call product_map(url) unless the user already gave exact steps.
3. Create a compact test plan with 3-12 steps. Prefer observable assertions.
4. Execute the plan with navigate, click, fill, press_key, screenshot, evaluate_js, get_console, and get_network.
5. After each important action, capture evidence: URL, page title/text signal, screenshot path, console errors, and failed network calls.
6. If selectors fail, inspect the page and adapt once before declaring a step blocked.
7. Return a Fagun-style report: verdict, steps run, evidence, bugs found, fixes, and residual risk.

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
- product_map(url) for business context and recommended journeys
- navigate(url), click(target), fill(selector, value), press_key(key)
- screenshot(full_page=true) for visual evidence
- evaluate_js(code) for page text, title, DOM checks, and custom assertions
- get_console(only_errors=true), get_network(only_problems=true)
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
        "evidence_to_collect": ["screenshot", "console_errors", "network_failures", "url", "title"],
    }
    return json.dumps(template, indent=2)
