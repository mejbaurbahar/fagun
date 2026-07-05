"""Unit tests for the UAT engine, readiness scorecard, and report formats."""

from __future__ import annotations

import json

from fagun import readiness, report, uat


# --------------------------------------------------------------- readiness
def _results(*findings):
    return [{"url": "https://x.test", "findings": list(findings)}]


def test_clean_site_is_production_ready():
    sc = readiness.build_scorecard(_results())
    assert sc["verdict"] == "Ready for Production"
    assert sc["overall_score"] == 100.0
    assert len(sc["categories"]) == 16


def test_security_highs_block_release():
    sc = readiness.build_scorecard(_results(
        {"severity": "high", "type": "leaked-secret", "detail": "AWS key"},
        {"severity": "high", "type": "sqli-error", "detail": "sqli"},
    ))
    assert sc["verdict"] == "Critical Issues Block Release"
    assert sc["categories"]["Security"]["score"] < 100


def test_blocked_journey_is_critical_for_business():
    sc = readiness.build_scorecard(_results(
        {"severity": "high", "type": "journey-blocked", "detail": "checkout step 3 failed"},
    ))
    # single blocker -> Not Ready; two -> Critical
    assert sc["verdict"] in ("Not Ready for Production", "Critical Issues Block Release")
    assert sc["categories"]["Business Logic"]["score"] < 100
    assert sc["categories"]["Customer Satisfaction"]["score"] < 100


def test_only_low_findings_is_minor():
    sc = readiness.build_scorecard(_results(
        {"severity": "low", "type": "seo", "detail": "missing description"},
    ))
    assert sc["verdict"] in ("Ready for Production", "Ready with Minor Improvements")


def test_recommendations_carry_why_and_fix():
    sc = readiness.build_scorecard(_results(
        {"severity": "high", "type": "a11y-inputLabel", "detail": "3 inputs no label"},
    ))
    recs = sc["recommendations"]
    assert recs and recs[0]["why"] and recs[0]["fix"]
    assert recs[0]["severity"] == "high"


def test_a11y_finding_hits_accessibility_category():
    sc = readiness.build_scorecard(_results(
        {"severity": "medium", "type": "a11y-contrast", "detail": "low contrast"},
    ))
    assert sc["categories"]["Accessibility"]["findings"] == 1
    assert sc["categories"]["Accessibility"]["score"] < 100


# ------------------------------------------------------------------ reports
def test_report_formats_dispatch_by_extension():
    results = _results({"severity": "high", "type": "xss", "detail": "reflected"})
    sc = readiness.build_scorecard(results)
    md = report.build_report(results, fmt="md", scorecard=sc)
    html = report.build_report(results, fmt="html", scorecard=sc)
    js = report.build_report(results, fmt="json", scorecard=sc)
    xml = report.build_report(results, fmt="xml", scorecard=sc)
    assert "Product Readiness" in md
    assert html.lstrip().startswith("<!doctype html>")
    assert "verdict" in html.lower()
    parsed = json.loads(js)
    assert parsed["readiness"]["verdict"]
    assert xml.startswith("<?xml") and "<testsuites" in xml and "<failure" in xml


def test_junit_marks_high_as_failure_low_as_pass():
    results = _results(
        {"severity": "high", "type": "xss", "detail": "bad"},
        {"severity": "low", "type": "seo", "detail": "meh"},
    )
    xml = report.build_junit(results)
    assert xml.count("<failure") == 1  # only the high finding fails


def test_write_report_picks_extension(tmp_path):
    results = _results({"severity": "medium", "type": "perf", "detail": "slow"})
    p = tmp_path / "out.html"
    report.write_report(results, str(p), scorecard=readiness.build_scorecard(results))
    assert p.read_text().lstrip().startswith("<!doctype html>")


# --------------------------------------------------------------------- uat
def test_personas_and_journeys_exist():
    names = {p["name"] for p in uat.list_personas()}
    assert {"mobile", "slow-internet", "keyboard-only", "screen-reader", "international"} <= names
    assert {"login", "register", "checkout", "search"} <= set(uat.list_journeys())


def test_every_persona_has_a_note_and_context():
    for name, p in uat.PERSONAS.items():
        assert p["note"] and "context" in p


def test_journey_templates_are_well_formed():
    for name, steps in uat.JOURNEY_TEMPLATES.items():
        assert steps and all("action" in s for s in steps)


def test_action_aliases_normalize():
    assert uat._ACTION_ALIASES["visit"] == "goto"
    assert uat._ACTION_ALIASES["tap"] == "click"
    assert uat._ACTION_ALIASES["expect_text"] == "assert_text"


async def test_style_tools_are_registered():
    from fagun.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"fagun_style_prompt", "fagun_style_schema", "fagun_render_response"} <= names
    assert {"fagun_security_prompt", "list_external_security_tools", "recommend_security_tools"} <= names
