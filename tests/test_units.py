"""Pure-logic unit tests — no browser required. Fast, run everywhere."""

from __future__ import annotations

import re

from fagun import format as fmt
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


def test_clip_and_dumps():
    assert fmt.clip("x" * 200, 10).endswith("…")
    assert fmt.dumps({"a": 1}) == '{"a":1}'


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
