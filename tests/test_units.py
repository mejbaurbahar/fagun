"""Pure-logic unit tests — no browser required. Fast, run everywhere."""

from __future__ import annotations

import re

import pytest

from fagun import format as fmt
from fagun import security_toolkit
from fagun import style
from fagun import testdata
from fagun.report import build_markdown


# ------------------------------------------------------------------- testdata
def test_cases_for_email_has_categories():
    cases = testdata.cases_for("email", "email")
    cats = {c.category for c in cases}
    assert {"valid", "invalid", "injection"} <= cats
    # every case carries a value, label, and a valid expect verdict
    for c in cases:
        assert c.label and c.value is not None
        assert c.expect in ("accept", "reject", "")  # "" = observe-only


def test_cases_for_unknown_type_falls_back_to_text():
    cases = testdata.cases_for("totally-unknown-type", "x")
    assert cases, "should still return generic text cases"


def test_name_heuristic_infers_email_for_text_field():
    # a text field named "email" should still get email cases
    cases = testdata.cases_for("text", "user_email")
    assert any("email:" in c.label for c in cases)


def test_injection_cases_are_observe_only():
    for t in ("email", "number", "text"):
        inj = [c for c in testdata.cases_for(t, t) if c.category == "injection"]
        assert inj, f"no injection cases for {t}"
        # injection payloads are observe-only — no accept/reject verdict invented
        assert all(c.expect == "" for c in inj)


# --------------------------------------------------------------------- format
def test_findings_block_counts_and_order():
    findings = [
        {"severity": "low", "type": "a", "detail": "d1"},
        {"severity": "high", "type": "b", "detail": "d2"},
        {"severity": "medium", "type": "c", "detail": "d3"},
    ]
    out = fmt.findings_block("https://x.test", findings, meta="m")
    assert "3 findings: 1H 1M 1L" in out
    # high must render before low
    assert out.index("b:") < out.index("a:")


def test_findings_block_caps():
    findings = [{"severity": "low", "type": "t", "detail": f"d{i}"} for i in range(60)]
    out = fmt.findings_block("u", findings, cap=40)
    assert "+20 more" in out


def test_findings_block_obeys_token_budget_env(monkeypatch):
    monkeypatch.setenv("FAGUN_FINDING_CAP", "2")
    monkeypatch.setenv("FAGUN_DETAIL_CHARS", "35")
    findings = [{"severity": "low", "type": "t", "detail": "x" * 100} for _ in range(5)]
    out = fmt.findings_block("https://example.test/path", findings)
    assert out.count("\n") == 3  # header + 2 findings + overflow marker
    assert "+3 more" in out
    assert "x" * 80 not in out


def test_render_multi_obeys_page_cap(monkeypatch):
    monkeypatch.setenv("FAGUN_PAGE_CAP", "2")
    results = [{"url": f"https://x.test/{i}", "ok": True, "findings": []} for i in range(5)]
    out = fmt.render_multi(results, terse=True, header="H")
    assert "+3 more pages" in out
    assert "https://x.test/4" not in out


def test_mini_mode_uses_lower_defaults(monkeypatch):
    monkeypatch.setenv("FAGUN_TERSE", "mini")
    assert fmt.finding_cap() == 12
    assert fmt.page_cap() == 6
    assert fmt.detail_chars() == 72


def test_clip_and_dumps():
    assert fmt.clip("x" * 200, 10).endswith("…")
    assert fmt.dumps({"a": 1}) == '{"a":1}'


# ---------------------------------------------------------------------- style
def test_style_prompt_and_schema_are_model_agnostic():
    prompt = style.style_prompt("json")
    schema = style.schema_json()
    parsed = __import__("json").loads(schema)
    assert "Fagun Style" in prompt
    assert "valid JSON" in prompt
    assert "summary" in parsed["required"]
    assert "test_cases" in parsed["properties"]


def test_render_response_outputs_fagun_sections():
    out = style.render_response({
        "summary": ["Fixed login validation"],
        "problem": "Users could submit blank email.",
        "solution": ["Require email before submit."],
        "test_cases": [{"name": "blank email", "type": "negative", "expected": "button stays disabled"}],
        "risks": ["Legacy browser validation differences."],
        "final_recommendation": "Ship after regression test passes.",
    }, title="Fagun Test")
    assert "# Fagun Test" in out
    assert "## Executive Summary" in out
    assert "## Test Cases" in out
    assert "`negative` blank email" in out
    assert "Ship after regression" in out


def test_coerce_payload_accepts_plain_text():
    payload = style.coerce_payload("plain answer")
    assert payload["summary"] == ["plain answer"]
    assert payload["final_recommendation"]


# ------------------------------------------------------------- security prompt
def test_security_tool_catalog_includes_requested_tools():
    names = {tool["name"] for tool in security_toolkit.EXTERNAL_TOOL_CATALOG}
    assert {
        "Loxs",
        "Skill Security Scanner",
        "Shannon",
        "Lonkero",
        "coffinxp/payloads",
        "RFC822 Email Validator",
        "LostFuzzer",
        "img-payloads",
        "customBsqli",
        "BeeXSS",
        "TimeVault",
        "NextSploit",
        "recon-skills",
    } <= names
    assert all(tool["repo"].startswith("https://github.com/") for tool in security_toolkit.EXTERNAL_TOOL_CATALOG)
    assert all(tool["integration_mode"].endswith("-adapter") for tool in security_toolkit.EXTERNAL_TOOL_CATALOG)


def test_security_platform_prompt_is_scope_gated():
    prompt = security_toolkit.security_platform_prompt().lower()
    assert "authorized targets only" in prompt
    assert "do not run every" in prompt
    assert "attack graph" in prompt
    assert "non-destructive" in prompt


def test_security_tool_filter_and_recommendations():
    xss_tools = security_toolkit.list_security_tools("xss")
    assert {tool["name"] for tool in xss_tools} >= {"Loxs", "BeeXSS"}

    rec = security_toolkit.recommend_security_tools(
        goal="Validate blind xss in query parameters and check Next.js CVE risk",
        target_profile_json='{"framework":"Next.js","forms":["search"]}',
    )
    names = {tool["name"] for tool in rec["tools"]}
    assert "BeeXSS" in names
    assert "NextSploit" in names

    recon_rec = security_toolkit.recommend_security_tools(
        goal="Use sector methodology for WordPress CORS XMLRPC JS secrets and metrics exposure recon",
        target_profile_json='{"cms":"WordPress","sector":"law firm"}',
    )
    recon_names = {tool["name"] for tool in recon_rec["tools"]}
    assert "recon-skills" in recon_names


def test_security_tool_catalog_renders_recon_skills_usage():
    out = security_toolkit.render_tool_catalog(security_toolkit.list_security_tools("sector methodology"))
    assert "recon-skills" in out
    assert "methodology-adapter" in out
    assert "read-only checklist" in out


def test_render_multi_totals():
    results = [
        {"url": "a", "ok": True, "findings": [{"severity": "high", "type": "x", "detail": "d"}]},
        {"url": "b", "ok": True, "findings": []},
    ]
    out = fmt.render_multi(results, terse=True, header="H")
    assert "2 pages" in out and "1 high" in out


# --------------------------------------------------------------------- report
def test_build_markdown_summary_and_evidence():
    results = [{
        "url": "https://x.test",
        "status": 200,
        "findings": [
            {"severity": "high", "type": "xss", "detail": "bad", "evidence": "saw it"},
            {"severity": "low", "type": "seo", "detail": "meh"},
        ],
    }]
    md = build_markdown(results)
    assert "# Fagun QA Report" in md
    assert "Pages checked: **1**" in md
    assert "1 high" in md
    assert "_evidence:_ saw it" in md


# ------------------------------------------------------- security detectors
def test_secret_patterns_match_known_samples():
    from fagun.security import _SECRET_PATTERNS

    samples = {
        "AWS access key": "AKIAIOSFODNN7EXAMPLE",
        "Stripe live secret key": "sk_live_" + "a" * 30,
        "GitHub token": "ghp_" + "a" * 36,
    }
    by_label = {label: rx for rx, label in _SECRET_PATTERNS}
    for label, sample in samples.items():
        assert by_label[label].search(sample), f"{label} pattern failed"


def test_sql_error_signature():
    from fagun.security import _SQL_ERRORS

    assert _SQL_ERRORS.search("You have an error in your SQL syntax near")
    assert not _SQL_ERRORS.search("totally normal page content")


def test_advsec_stack_and_lfi_signatures():
    from fagun.advsec import _LFI_SIG, _STACK

    assert _LFI_SIG.search("root:x:0:0:root:/root:/bin/bash")
    assert _STACK.search("Traceback (most recent call last):")


def test_ssti_expectations_are_49():
    from fagun.advsec import _SSTI

    for payload, expect in _SSTI:
        assert expect == "49"
        assert "7*7" in payload


def test_advanced_scan_skips_dom_checks_after_load_failure():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fagun import advsec

    class _Page:
        request = object()

        async def goto(self, *a, **k):
            raise RuntimeError("no document")

    async def _no_findings(url):
        return []

    with patch.object(advsec.manager, "page", new_callable=AsyncMock, return_value=_Page()):
        with patch.object(advsec, "check_csp", _no_findings), \
             patch.object(advsec, "check_clickjacking", _no_findings), \
             patch.object(advsec, "check_http_methods", _no_findings), \
             patch.object(advsec, "check_cache", _no_findings), \
             patch.object(advsec, "check_host_header", _no_findings), \
             patch.object(advsec, "check_crlf", _no_findings), \
             patch.object(advsec, "check_path_traversal", _no_findings), \
             patch.object(advsec, "check_ssti", _no_findings), \
             patch.object(advsec, "check_cmdi", _no_findings), \
             patch.object(advsec, "check_graphql", _no_findings), \
             patch.object(advsec, "check_error_disclosure", _no_findings), \
             patch.object(advsec, "check_sensitive_url", _no_findings):
            r = asyncio.run(advsec.advanced_scan("https://x.test"))

    assert any(f["type"] == "scan-warning" for f in r["findings"])


# --------------------------------------------------------------------- scope
def test_scope_allows_all_by_default(monkeypatch):
    from fagun import scope

    monkeypatch.delenv("FAGUN_SCOPE", raising=False)
    monkeypatch.delenv("FAGUN_SCOPE_DENY", raising=False)
    assert scope.in_scope("https://anything.example/x")
    assert scope.in_scope("file:///tmp/x.html")  # local fixtures never blocked
    assert not scope.is_configured()


def test_scope_allowlist_includes_subdomains(monkeypatch):
    from fagun import scope

    monkeypatch.setenv("FAGUN_SCOPE", "example.com")
    monkeypatch.delenv("FAGUN_SCOPE_DENY", raising=False)
    assert scope.in_scope("https://example.com/a")
    assert scope.in_scope("https://api.example.com/a")
    assert not scope.in_scope("https://evil.test/a")
    with pytest.raises(PermissionError):
        scope.guard("https://evil.test/a")


def test_scope_deny_overrides_allow(monkeypatch):
    from fagun import scope

    monkeypatch.setenv("FAGUN_SCOPE", "example.com")
    monkeypatch.setenv("FAGUN_SCOPE_DENY", "internal.example.com")
    assert scope.in_scope("https://example.com/a")
    assert not scope.in_scope("https://internal.example.com/a")


# ------------------------------------------------------------ secret severity
def test_jwt_secret_is_medium_not_high():
    # a bare JWT is often a public/anon token — should not be a "high" leak.
    import asyncio
    from unittest.mock import AsyncMock, patch

    from fagun import security

    jwt = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    html = f"<script>const t='{jwt}';</script>"

    class _Page:
        async def goto(self, *a, **k):
            return None

        async def content(self):
            return html

        async def eval_on_selector_all(self, *a, **k):
            return []

    with patch.object(security.manager, "page", new_callable=AsyncMock, return_value=_Page()):
        findings = asyncio.run(security.scan_secrets("https://x.test"))
    jwts = [f for f in findings if "JWT" in f["detail"]]
    assert jwts and all(f["severity"] == "medium" for f in jwts)


# ------------------------------------------------------------- sitemap parsing
def test_sitemap_and_robots_regexes():
    from fagun.qa import _LOC_RE, _SITEMAP_RE

    xml = "<urlset><url><loc>https://x.test/a</loc></url><url><loc> https://x.test/b </loc></url></urlset>"
    assert _LOC_RE.findall(xml) == ["https://x.test/a", "https://x.test/b"]
    robots = "User-agent: *\nDisallow: /admin\nSitemap: https://x.test/sitemap.xml\n"
    assert _SITEMAP_RE.findall(robots) == ["https://x.test/sitemap.xml"]


def test_pytest_import_path_is_configured():
    from pathlib import Path

    pyproject = Path("pyproject.toml").read_text()
    assert 'pythonpath = ["src"]' in pyproject
    assert 'addopts = "--strict-config --strict-markers"' in pyproject


def test_fagun_skill_requires_auto_chrome_and_full_final_output():
    from pathlib import Path

    skill = Path("src/fagun/data/skill.md").read_text()
    assert "Automatic Chrome behavior" in skill
    assert "Do not ask the user to\nrun `fagun connect to my Chrome`" in skill
    assert "Final output requirement" in skill
    assert "Every reproduced finding, not just the top three" in skill


def test_website_documents_auto_chrome_and_full_output():
    from pathlib import Path

    home = Path("docs/index.html").read_text()
    docs = Path("docs/docs.html").read_text()
    assert "auto Chrome MCP" in home
    assert "full findings + evidence printed in chat" in home
    assert "fagun deep test https://example.com" in docs
    assert "Users do not need to run <code>fagun connect to my Chrome</code> first" in docs
    assert "pip install --upgrade fagun" in home
    assert "uvx --upgrade --reinstall fagun init" in home
    assert "safe external security-tool planning" in home
    assert 'id="workflow"' in home
    assert 'id="workflow"' in docs
    assert "Chrome DevTools MCP auto-connects to signed-in Chrome" in docs
    assert "Full Fagun answer in chat plus HTML, Markdown, JSON, or JUnit report" in home


def test_readme_and_install_docs_prefer_init_and_cover_pip():
    from pathlib import Path

    readme = Path("README.md").read_text()
    install_doc = Path("install.md").read_text()
    assert "uvx fagun init" in readme
    assert "pip install --upgrade fagun" in readme
    assert "uvx --upgrade --reinstall fagun init" in readme
    assert "uvx fagun setup      # installs" not in readme
    assert "uvx fagun init" in install_doc
    assert "pip install --upgrade fagun" in install_doc
    assert "uvx --upgrade --reinstall fagun init" in install_doc
    assert "uvx fagun setup" not in install_doc


def test_package_version_bumped_for_release():
    from pathlib import Path

    pyproject = Path("pyproject.toml").read_text()
    init_py = Path("src/fagun/__init__.py").read_text()
    assert 'version = "0.9.1"' in pyproject
    assert '__version__ = "0.9.1"' in init_py


# ------------------------------------------------------------------- sessions
def test_session_summary_counts():
    from fagun import session

    state = {"cookies": [{"name": "a"}, {"name": "b"}],
             "origins": [{"origin": "https://x", "localStorage": [{"name": "k"}]}]}
    s = session._summary(state)
    assert "2 cookie" in s and "1 localStorage" in s and "1 origin" in s


def test_session_name_is_sanitized():
    from fagun import session

    assert session._safe("acme/../etc") == "acmeetc"
    assert session._safe("") == "default"
