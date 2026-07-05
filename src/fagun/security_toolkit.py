"""Security prompt and external-tool catalog for Fagun.

The catalog is intentionally orchestration-only: Fagun can explain, recommend,
and plan tool usage, while active execution remains scope-gated elsewhere.
"""

from __future__ import annotations

import json
from typing import Any


AUTHORIZED_USE = (
    "Only test systems you own or have explicit permission to assess. Keep "
    "active probes in scope, rate-limited, reversible, and non-destructive."
)

SECURITY_PLATFORM_PROMPT = """You are Fagun AI Security Engineer.

Mission:
Build and operate an advanced AI-powered security testing and bug-hunting workflow
for authorized targets only. Think like a senior penetration tester, security
researcher, QA engineer, product engineer, and DevSecOps reviewer. Do not behave
like a scanner runner.

Operating rules:
1. Confirm the target is authorized and in scope before active testing.
2. Start with passive understanding: target purpose, user roles, trust boundaries,
   technologies, auth model, API shape, client-side code, assets, and risky flows.
3. Build an attack graph before choosing tools.
4. Select the smallest useful tool set for the detected surface. Do not run every
   tool blindly.
5. Prefer non-destructive checks. Avoid state-changing actions unless the user
   explicitly authorizes them and the test plan explains rollback.
6. Correlate, deduplicate, and validate findings. Mark hypotheses separately from
   reproduced evidence.
7. Report severity, confidence, affected asset, reproduction, observed behavior,
   expected behavior, business impact, remediation, and regression tests.
8. Keep chat compact. Put large logs, screenshots, payload lists, and raw evidence
   into files or reports.

Assessment coverage:
- Target profiling: framework, CMS, frontend/backend stack, APIs, CDN/proxy/WAF,
  auth/session/JWT/OAuth, cloud signals, third-party integrations, JavaScript
  libraries, exposed files, source maps, and dependency risks.
- Recon: crawl, sitemap/robots, endpoints, parameters, forms, GraphQL, REST,
  hidden APIs, admin areas, upload/download handlers, webhooks, payment/user flows,
  and sensitive data paths.
- Vulnerability planning: auth bypass, authorization/IDOR, logic flaws, validation
  gaps, XSS, redirect, SQLi signals, LFI/path traversal, SSTI/cmdi signals, CRLF,
  CORS/header issues, CSP/clickjacking, exposed secrets, dependency/supply-chain,
  prompt injection, AI workflow abuse, race-condition candidates, and performance
  bottlenecks.
- Fuzzing design: numeric, Unicode, UTF-8/UTF-16, JSON, XML, multipart, headers,
  cookies, JWT, URL encoding, double encoding, oversized payloads, recursion,
  malformed MIME, and boundary/empty/null values.

External tool strategy:
Use Fagun's external security tool catalog as adapters, not as blind execution.
For each candidate tool, explain why it is relevant, required input, safety limits,
expected evidence, validation method, and fallback if it is unavailable.

Output in Fagun Style:
Executive Summary, Target Profile, Attack Graph, Tool Plan, Findings, Evidence,
Remediation, Test Cases, Risks, Production Impact, and Final Recommendation.
"""


EXTERNAL_TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "Loxs",
        "repo": "https://github.com/coffinxp/loxs",
        "category": "multi-vulnerability-scanner",
        "signals": ["lfi", "open redirect", "sqli", "xss", "crlf", "parameters"],
        "use_when": "A scoped URL list has query parameters or endpoints suitable for broad non-destructive triage.",
        "safe_default": "Plan or import results first; run only against an allowlisted URL set with conservative rate limits.",
        "integration_mode": "external-adapter",
    },
    {
        "name": "Skill Security Scanner",
        "repo": "https://github.com/Alittlefatwhale/skill-security-scanner",
        "category": "ai-supply-chain-audit",
        "signals": ["claude skill", "prompt injection", "tool abuse", "malicious skill", "supply chain"],
        "use_when": "Auditing AI skills, agent instructions, tool manifests, and local automation bundles.",
        "safe_default": "Read-only source review; never execute untrusted skill code while auditing it.",
        "integration_mode": "source-review-adapter",
    },
    {
        "name": "Shannon",
        "repo": "https://github.com/momika233/shannon",
        "category": "ai-security-agent",
        "signals": ["autonomous", "exploit validation", "source-aware", "web app"],
        "use_when": "Advanced authorized research where source-aware reasoning and validation are needed.",
        "safe_default": "Use as a planning/validation reference unless explicit scope and execution limits are configured.",
        "integration_mode": "agent-harness-adapter",
    },
    {
        "name": "Lonkero",
        "repo": "https://github.com/momika233/lonkero",
        "category": "attack-surface-scanner",
        "signals": ["scanner", "attack surface", "rust", "modular", "recon"],
        "use_when": "Professional-grade attack-surface mapping for a clearly scoped domain or app.",
        "safe_default": "Start with low-rate discovery and Fagun deduplication before deeper probes.",
        "integration_mode": "scanner-adapter",
    },
    {
        "name": "coffinxp/payloads",
        "repo": "https://github.com/coffinxp/payloads",
        "category": "payload-corpus",
        "signals": ["payloads", "wordlists", "xss", "sqli", "lfi", "ssrf", "admin", "backup"],
        "use_when": "Fuzzing needs a curated corpus for authorized validation and negative test generation.",
        "safe_default": "Sample and mutate context-aware payloads; avoid dumping entire corpora into model context.",
        "integration_mode": "payload-corpus-adapter",
    },
    {
        "name": "RFC822 Email Validator",
        "repo": "https://github.com/coffinxp/RFC822-Email-Validator",
        "category": "input-validation",
        "signals": ["email", "registration", "login", "validation", "rfc822"],
        "use_when": "Testing email fields, registration, invitations, password reset, and account recovery workflows.",
        "safe_default": "Generate validation cases only; do not send mail unless a test mailbox is configured.",
        "integration_mode": "validation-adapter",
    },
    {
        "name": "LostFuzzer",
        "repo": "https://github.com/coffinxp/lostfuzzer",
        "category": "dast-fuzzing",
        "signals": ["fuzzer", "nuclei", "passive urls", "dast"],
        "use_when": "A passive URL inventory exists and needs template-based DAST triage.",
        "safe_default": "Run passive/low-risk templates first; require explicit approval for noisy or stateful templates.",
        "integration_mode": "fuzzing-adapter",
    },
    {
        "name": "img-payloads",
        "repo": "https://github.com/coffinxp/img-payloads",
        "category": "file-upload-testing",
        "signals": ["image", "upload", "metadata", "polyglot", "file validation"],
        "use_when": "Testing authorized image upload validation, MIME handling, metadata stripping, and file processing.",
        "safe_default": "Use inert samples first and verify server-side validation without harmful content.",
        "integration_mode": "payload-corpus-adapter",
    },
    {
        "name": "customBsqli",
        "repo": "https://github.com/coffinxp/customBsqli",
        "category": "sqli-validation",
        "signals": ["blind sqli", "sqli", "time-based", "database"],
        "use_when": "Fagun has a strong SQLi signal and needs scoped blind-SQLi confirmation planning.",
        "safe_default": "Prefer timing-safe confirmation and strict rate limits; do not extract data.",
        "integration_mode": "validation-adapter",
    },
    {
        "name": "BeeXSS",
        "repo": "https://github.com/AnonKryptiQuz/BeeXSS",
        "category": "xss-validation",
        "signals": ["blind xss", "xss", "parameters", "admin panel", "callbacks"],
        "use_when": "Testing authorized reflected/stored/blind XSS paths with callback infrastructure available.",
        "safe_default": "Use owned callback endpoints and clearly label test markers; avoid third-party targets.",
        "integration_mode": "validation-adapter",
    },
    {
        "name": "TimeVault",
        "repo": "https://github.com/AnonKryptiQuz/TimeVault",
        "category": "historical-recon",
        "signals": ["wayback", "archive", "information disclosure", "old urls"],
        "use_when": "Looking for historical URLs, leaked paths, removed files, or stale endpoints for an authorized domain.",
        "safe_default": "Passive archive discovery only; validate live exposure with read-only checks.",
        "integration_mode": "passive-recon-adapter",
    },
    {
        "name": "NextSploit",
        "repo": "https://github.com/AnonKryptiQuz/NextSploit",
        "category": "framework-cve-check",
        "signals": ["next.js", "cve-2025-29927", "middleware", "bypass"],
        "use_when": "Fingerprinting indicates Next.js and the assessment includes framework CVE validation.",
        "safe_default": "Check version/config exposure first; active validation requires explicit authorization.",
        "integration_mode": "cve-validation-adapter",
    },
]


def security_platform_prompt() -> str:
    """Return the improved reusable prompt for advanced security testing."""
    return SECURITY_PLATFORM_PROMPT.strip() + "\n\nSafety baseline: " + AUTHORIZED_USE


def list_security_tools(category: str = "") -> list[dict[str, Any]]:
    """Return the external tool catalog, optionally filtered by category/signal."""
    needle = (category or "").strip().lower()
    if not needle:
        return list(EXTERNAL_TOOL_CATALOG)
    out: list[dict[str, Any]] = []
    for tool in EXTERNAL_TOOL_CATALOG:
        haystack = " ".join([
            tool["name"],
            tool["category"],
            " ".join(tool.get("signals", [])),
            tool.get("use_when", ""),
        ]).lower()
        if needle in haystack:
            out.append(tool)
    return out


def recommend_security_tools(goal: str = "", target_profile_json: str = "") -> dict[str, Any]:
    """Recommend catalog tools from a text goal and optional target profile JSON."""
    text = goal or ""
    profile: Any = {}
    if target_profile_json:
        try:
            profile = json.loads(target_profile_json)
            text += " " + json.dumps(profile)
        except Exception:
            text += " " + target_profile_json
    text_l = text.lower()

    scored: list[tuple[int, dict[str, Any]]] = []
    for tool in EXTERNAL_TOOL_CATALOG:
        score = 0
        for signal in tool.get("signals", []):
            if signal.lower() in text_l:
                score += 3
            else:
                for token in signal.lower().replace("-", " ").split():
                    if len(token) > 2 and token in text_l:
                        score += 1
        if tool["category"].replace("-", " ") in text_l:
            score += 2
        if score:
            scored.append((score, tool))

    if not scored:
        defaults = ["TimeVault", "Lonkero", "coffinxp/payloads", "Skill Security Scanner"]
        chosen = [t for t in EXTERNAL_TOOL_CATALOG if t["name"] in defaults]
    else:
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        chosen = [tool for _score, tool in scored[:5]]

    return {
        "safety": AUTHORIZED_USE,
        "goal": goal,
        "tools": chosen,
        "workflow": [
            "Confirm scope and allowed test intensity.",
            "Profile target and build an attack graph.",
            "Use the selected tools only where the surface justifies them.",
            "Deduplicate outputs and validate with least-intrusive evidence.",
            "Report confidence, impact, remediation, and regression tests.",
        ],
    }


def render_tool_catalog(tools: list[dict[str, Any]] | None = None) -> str:
    """Render tools as compact Markdown for MCP clients."""
    rows = tools if tools is not None else EXTERNAL_TOOL_CATALOG
    lines = ["# Fagun External Security Tool Catalog", "", f"Safety: {AUTHORIZED_USE}", ""]
    for tool in rows:
        lines += [
            f"## {tool['name']}",
            f"- Category: `{tool['category']}`",
            f"- Repo: {tool['repo']}",
            f"- Use when: {tool['use_when']}",
            f"- Safe default: {tool['safe_default']}",
            f"- Integration: `{tool['integration_mode']}`",
            "",
        ]
    return "\n".join(lines).strip() + "\n"


def render_recommendation(recommendation: dict[str, Any]) -> str:
    """Render a tool recommendation into Fagun-style Markdown."""
    lines = [
        "# Fagun Security Tool Plan",
        "",
        f"Safety: {recommendation['safety']}",
        "",
        "## Recommended Tools",
        "",
    ]
    for tool in recommendation["tools"]:
        lines.append(f"- **{tool['name']}** (`{tool['category']}`): {tool['use_when']}")
    lines += ["", "## Workflow", ""]
    lines.extend(f"- {step}" for step in recommendation["workflow"])
    return "\n".join(lines).strip() + "\n"
