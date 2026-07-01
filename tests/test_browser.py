"""Browser-backed smoke tests over a local file:// fixture.

Skipped automatically if the Playwright Chromium engine isn't installed, so the
pure-logic suite still runs on any machine. Run `python -m playwright install
chromium` to enable these.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fagun.browser import manager

FIXTURE = (Path(__file__).parent / "fixtures" / "bad.html").resolve().as_uri()


async def _browser_available() -> bool:
    try:
        await manager.start(headless=True)
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _browser():
    # Function-scoped: a fresh browser per test avoids event-loop-scope mismatches
    # between pytest-asyncio's function loop and a module-scoped async fixture.
    if not await _browser_available():
        pytest.skip("Playwright Chromium not installed")
    yield
    await manager.stop()


async def test_a11y_audit_catches_seeded_problems():
    from fagun.a11y import audit

    r = await audit(FIXTURE, navigate=True)
    types = {f["type"] for f in r["findings"]}
    # the fixture seeds each of these on purpose
    assert "a11y-imgAlt" in types        # <img> with no alt
    assert "a11y-inputLabel" in types    # inputs with no label
    assert "a11y-emptyControl" in types  # empty <button>
    assert "a11y-dupId" in types         # duplicate id="dup"
    assert "a11y-noZoom" in types        # user-scalable=no
    # every finding must carry severity + type + detail
    for f in r["findings"]:
        assert f["severity"] in ("high", "medium", "low")
        assert f["type"] and f["detail"]


async def test_run_qa_returns_ok_with_findings():
    from fagun.qa import run_qa

    r = await run_qa(FIXTURE)
    assert r["ok"] is True
    assert isinstance(r["findings"], list)
    # a11y findings are folded into run_qa
    assert any(f["type"].startswith("a11y-") for f in r["findings"])


async def test_test_forms_flags_insecure_get_password():
    from fagun.qa import test_forms

    r = await test_forms(FIXTURE)
    details = " ".join(f["detail"] for f in r["findings"])
    # form posts a password over GET to http:// — both are high-severity
    assert "password over GET" in details or "insecure http" in details


async def test_log_buffers_are_capped():
    from collections import deque

    # ring buffers, not unbounded lists
    assert isinstance(manager.console, deque)
    assert isinstance(manager.network, deque)
    assert manager.console.maxlen and manager.console.maxlen >= 100


# ------------------------------------------------------------------ UAT layer
async def test_run_journey_completes_and_asserts():
    from fagun.uat import run_journey

    steps = [
        {"action": "goto", "url": FIXTURE, "label": "open fixture"},
        {"action": "assert_text", "target": "low-contrast paragraph", "label": "body text present"},
        {"action": "fill", "target": "input[name=username]", "value": "alice", "label": "enter user"},
        {"action": "assert_visible", "target": "form", "label": "form visible"},
    ]
    r = await run_journey(steps, name="smoke", screenshots=False)
    assert r["completed"] is True
    assert r["passed"] == 4


async def test_run_journey_reports_blocked_step():
    from fagun.uat import run_journey

    steps = [
        {"action": "goto", "url": FIXTURE, "label": "open"},
        {"action": "assert_text", "target": "this text does not exist anywhere", "label": "bad assert"},
    ]
    r = await run_journey(steps, name="fail", screenshots=False)
    assert r["completed"] is False
    assert any(f["type"] == "journey-blocked" for f in r["findings"])


async def test_keyboard_walk_finds_focusables():
    from fagun.uat import keyboard_walk

    r = await keyboard_walk(FIXTURE)
    # fixture has links, inputs, button -> some focusable elements
    assert r["focusable"] >= 3
    assert isinstance(r["findings"], list)


async def test_emulate_persona_sets_mobile_viewport():
    from fagun.uat import emulate_persona

    r = await emulate_persona("mobile")
    assert r["ok"] is True
    assert r["applied"]["mobile"] is True
    page = await manager.page()
    assert page.viewport_size["width"] == 390
    # reset to desktop so later ordering doesn't matter
    await emulate_persona("desktop")
