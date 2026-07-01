"""UAT engine — use the product like a real end user, not just a bug scanner.

Three capabilities the AI drives:

* :func:`emulate_persona` — put the browser into a *real* configuration for a
  given kind of user (mobile, slow internet, low-end device, international,
  reduced-motion / screen-reader-style, keyboard-only …). Uses genuine Playwright
  device + CDP network/CPU throttling + media emulation, so what the AI then sees
  is what that user would actually see.

* :func:`run_journey` — walk a complete user journey step by step (register,
  login, search, checkout …). Every step records whether it succeeded, a
  screenshot, console errors and failed requests that happened *during that
  step*, and how long it took. Failed expectations become friction findings.
  Nothing is faked — a step "passes" only if the browser actually did it.

* :func:`keyboard_walk` — tab through the page like a keyboard-only / screen-
  reader user and report focus-visibility gaps, focus traps, and unreachable
  controls.

The higher-level judgement (is this intuitive? would a customer be happy?) is the
AI's job — these tools give it the real end-user vantage point and the evidence.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from typing import Any, Optional

from .browser import manager

# --------------------------------------------------------------------- personas
# Real device / network / media configurations. `context` keys go to
# new_context(); `network` picks a throttle profile; `cpu` is a CDP slowdown
# factor; `media` sets emulate_media kwargs; `note` explains who this models.
_UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
_UA_ANDROID = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
_UA_IPAD = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

PERSONAS: dict[str, dict[str, Any]] = {
    "desktop": {
        "note": "Standard desktop visitor, fast connection.",
        "context": {"viewport": {"width": 1920, "height": 1080}},
    },
    "first-time": {
        "note": "First-time visitor — fresh context, no cookies/storage.",
        "context": {"viewport": {"width": 1366, "height": 768}},
        "fresh": True,
    },
    "mobile": {
        "note": "Mobile phone user (iPhone-class), touch, small screen.",
        "context": {
            "viewport": {"width": 390, "height": 844}, "device_scale_factor": 3,
            "is_mobile": True, "has_touch": True, "user_agent": _UA_IPHONE,
        },
    },
    "android-mobile": {
        "note": "Android phone user (Pixel-class).",
        "context": {
            "viewport": {"width": 412, "height": 915}, "device_scale_factor": 2.6,
            "is_mobile": True, "has_touch": True, "user_agent": _UA_ANDROID,
        },
    },
    "tablet": {
        "note": "Tablet user (iPad-class), touch, medium screen.",
        "context": {
            "viewport": {"width": 820, "height": 1180}, "device_scale_factor": 2,
            "is_mobile": True, "has_touch": True, "user_agent": _UA_IPAD,
        },
    },
    "slow-internet": {
        "note": "User on a slow/unstable connection (throttled to ~slow 3G).",
        "context": {"viewport": {"width": 1366, "height": 768}},
        "network": "slow-3g",
    },
    "low-end": {
        "note": "Cheap/old phone: small screen, slow CPU (6x), slow network.",
        "context": {
            "viewport": {"width": 360, "height": 640}, "device_scale_factor": 2,
            "is_mobile": True, "has_touch": True, "user_agent": _UA_ANDROID,
        },
        "network": "slow-3g", "cpu": 6,
    },
    "keyboard-only": {
        "note": "Keyboard-only user (no mouse) — pair with keyboard_walk.",
        "context": {"viewport": {"width": 1366, "height": 768}},
    },
    "screen-reader": {
        "note": "Assistive-tech / reduced-motion user; forced-colors on.",
        "context": {"viewport": {"width": 1366, "height": 768}, "reduced_motion": "reduce"},
        "media": {"reduced_motion": "reduce", "forced_colors": "active"},
    },
    "dark-mode": {
        "note": "User with OS dark theme enabled.",
        "context": {"viewport": {"width": 1440, "height": 900}, "color_scheme": "dark"},
        "media": {"color_scheme": "dark"},
    },
    "international": {
        "note": "Non-English / other-region user (locale + Accept-Language).",
        "context": {
            "viewport": {"width": 1366, "height": 768}, "locale": "de-DE",
            "timezone_id": "Europe/Berlin",
            "extra_http_headers": {"Accept-Language": "de-DE,de;q=0.9,en;q=0.5"},
        },
    },
}

# Network throttle profiles (Chrome DevTools Protocol Network.emulateNetworkConditions).
_NET_PROFILES = {
    "slow-3g": {"latency": 400, "downloadThroughput": int(400 * 1024 / 8), "uploadThroughput": int(400 * 1024 / 8)},
    "fast-3g": {"latency": 150, "downloadThroughput": int(1.6 * 1024 * 1024 / 8), "uploadThroughput": int(750 * 1024 / 8)},
    "offline": {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
}


def list_personas() -> list[dict[str, str]]:
    return [{"name": k, "note": v["note"]} for k, v in PERSONAS.items()]


async def emulate_persona(name: str) -> dict[str, Any]:
    """Reconfigure the browser to match a persona. Returns what was applied."""
    key = name.strip().lower()
    persona = PERSONAS.get(key)
    if persona is None:
        return {"ok": False, "error": f"unknown persona {name!r}",
                "available": list(PERSONAS)}
    ctx_opts = dict(persona.get("context", {}))
    await manager.new_context_with(**ctx_opts)
    applied = {"viewport": ctx_opts.get("viewport"), "mobile": ctx_opts.get("is_mobile", False)}

    # Media emulation (reduced motion, color scheme, forced colors).
    media = persona.get("media")
    if media:
        try:
            await (await manager.page()).emulate_media(**media)
            applied["media"] = media
        except Exception as e:
            applied["media_error"] = str(e)

    # Network + CPU throttling via CDP (Chromium only; silently skipped elsewhere).
    net = persona.get("network")
    cpu = persona.get("cpu")
    if net or cpu:
        client = await manager.cdp()
        if client is None:
            applied["throttle"] = "unsupported on this engine"
        else:
            if net and net in _NET_PROFILES:
                try:
                    await client.send("Network.enable")
                    prof = {"offline": False, **_NET_PROFILES[net]}
                    await client.send("Network.emulateNetworkConditions", prof)
                    applied["network"] = net
                except Exception as e:
                    applied["network_error"] = str(e)
            if cpu:
                try:
                    await client.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
                    applied["cpu_throttle"] = f"{cpu}x"
                except Exception as e:
                    applied["cpu_error"] = str(e)
    return {"ok": True, "persona": key, "note": persona["note"], "applied": applied}


# ---------------------------------------------------------------- journey runner
_ACTION_ALIASES = {
    "visit": "goto", "open": "goto", "navigate": "goto",
    "type": "fill", "enter": "fill", "input": "fill",
    "tap": "click",
    "expect_text": "assert_text", "see_text": "assert_text", "contains": "assert_text",
    "expect_url": "assert_url",
    "expect_visible": "assert_visible", "visible": "assert_visible",
}


def _screenshot_path(tag: str) -> str:
    safe = "".join(c for c in tag if c.isalnum() or c in "-_")[:40] or "step"
    return os.path.join(tempfile.gettempdir(), f"fagun-uat-{safe}-{int(time.time()*1000) % 10**7}.png")


async def _do_step(page, step: dict[str, Any]) -> tuple[bool, str]:
    """Execute one journey step; return (ok, human detail). Never raises."""
    action = _ACTION_ALIASES.get(str(step.get("action", "")).lower(), str(step.get("action", "")).lower())
    target = step.get("target") or step.get("selector") or step.get("url") or step.get("text") or ""
    value = step.get("value", "")
    try:
        if action == "goto":
            resp = await page.goto(target, wait_until="load", timeout=30000)
            code = resp.status if resp else "?"
            if resp and resp.status >= 400:
                return False, f"goto {target} → HTTP {code}"
            return True, f"loaded {page.url} ({code})"
        if action == "click":
            try:
                await page.click(target, timeout=8000)
            except Exception:
                await page.get_by_text(target, exact=False).first.click(timeout=8000)
            return True, f"clicked {target!r} → {page.url}"
        if action == "fill":
            try:
                await page.fill(target, value, timeout=8000)
            except Exception:
                await page.get_by_label(target).fill(value, timeout=8000)
            return True, f"filled {target!r}"
        if action == "select":
            await page.select_option(target, value, timeout=8000)
            return True, f"selected {value!r} in {target!r}"
        if action == "press":
            await page.keyboard.press(target or value)
            return True, f"pressed {target or value}"
        if action == "wait":
            if isinstance(target, str) and target and not target.isdigit():
                await page.wait_for_selector(target, timeout=15000)
                return True, f"waited for {target!r}"
            ms = int(target or value or 1000)
            await page.wait_for_timeout(ms)
            return True, f"waited {ms}ms"
        if action == "assert_text":
            body = await page.text_content("body") or ""
            ok = target.lower() in body.lower()
            return ok, (f"found text {target!r}" if ok else f"MISSING expected text {target!r}")
        if action == "assert_no_text":
            body = await page.text_content("body") or ""
            ok = target.lower() not in body.lower()
            return ok, (f"correctly absent: {target!r}" if ok else f"UNEXPECTED text present {target!r}")
        if action == "assert_url":
            ok = target.lower() in page.url.lower()
            return ok, (f"url contains {target!r}" if ok else f"url {page.url} lacks {target!r}")
        if action == "assert_visible":
            try:
                await page.wait_for_selector(target, state="visible", timeout=8000)
                return True, f"visible: {target!r}"
            except Exception:
                return False, f"NOT visible: {target!r}"
        if action == "screenshot":
            return True, "screenshot"
        return False, f"unknown action {action!r}"
    except Exception as e:
        return False, f"{action} failed: {type(e).__name__}: {e}"


async def run_journey(steps: list[dict[str, Any]], name: str = "journey",
                      screenshots: bool = True) -> dict[str, Any]:
    """Run a full user journey step-by-step, capturing real evidence per step."""
    page = await manager.page()
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    passed = failed = 0

    for i, step in enumerate(steps):
        manager.clear_logs()
        t0 = time.perf_counter()
        ok, detail = await _do_step(page, step)
        ms = round((time.perf_counter() - t0) * 1000)

        console_errs = [c.text[:200] for c in manager.console if c.type == "error"]
        net_fails = [f"{n.status or n.failure} {n.url}" for n in manager.network
                     if n.failure or (n.status and n.status >= 400)]

        shot = None
        if screenshots:
            try:
                shot = _screenshot_path(f"{name}-{i}")
                await page.screenshot(path=shot)
            except Exception:
                shot = None

        label = step.get("label") or f"{step.get('action')} {step.get('target') or step.get('url') or ''}".strip()
        entry = {"i": i, "label": label[:80], "ok": ok, "detail": detail, "ms": ms,
                 "console_errors": len(console_errs), "network_failures": len(net_fails)}
        if shot:
            entry["screenshot"] = shot
        results.append(entry)

        if ok:
            passed += 1
        else:
            failed += 1
            findings.append({"severity": "high", "type": "journey-blocked",
                             "detail": f"step {i} ({label[:50]}): {detail}",
                             "evidence": (shot or "no screenshot")})
        # A step can succeed yet surface errors — real end-user friction.
        for ce in console_errs[:3]:
            findings.append({"severity": "medium", "type": "journey-console-error",
                             "detail": f"step {i}: JS error during '{label[:40]}'", "evidence": ce})
        for nf in net_fails[:3]:
            findings.append({"severity": "medium", "type": "journey-request-failed",
                             "detail": f"step {i}: request failed during '{label[:40]}'", "evidence": nf[:160]})
        if ms > 5000 and ok:
            findings.append({"severity": "low", "type": "journey-slow",
                             "detail": f"step {i} ('{label[:40]}') took {ms}ms (>5s) — user waits", "evidence": f"{ms}ms"})
        if not ok:
            break  # journey is blocked; later steps depend on this one

    completed = failed == 0
    return {"journey": name, "steps_total": len(steps), "steps_run": len(results),
            "passed": passed, "failed": failed, "completed": completed,
            "step_log": results, "findings": findings}


# ---------------------------------------------------------------- keyboard walk
_KEYBOARD_JS = r"""
() => {
  const focusables = [...document.querySelectorAll(
    'a[href],button,input,select,textarea,[tabindex],[contenteditable="true"]')]
    .filter(e => !e.disabled && e.offsetParent !== null &&
                 (e.getAttribute('tabindex') === null || +e.getAttribute('tabindex') >= 0));
  return {reachable: focusables.length};
}
"""


async def keyboard_walk(url: str, max_stops: int = 60) -> dict[str, Any]:
    """Tab through the page like a keyboard user. Reports focus-visibility gaps,
    traps, and how far the keyboard can actually reach."""
    page = await manager.page()
    await page.goto(url, wait_until="load", timeout=30000)
    counts = await page.evaluate(_KEYBOARD_JS)
    reachable = counts.get("reachable", 0)

    await page.evaluate("() => { const b=document.body; b && b.focus(); document.activeElement && document.activeElement.blur(); }")
    seen: list[str] = []
    no_focus_style = 0
    stops = 0
    last = None
    trap = False
    for _ in range(min(max_stops, max(reachable + 5, 10))):
        await page.keyboard.press("Tab")
        info = await page.evaluate(r"""
        () => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const id = el.id ? '#'+el.id : '';
          const sel = el.tagName.toLowerCase() + id;
          const st = getComputedStyle(el);
          const hasOutline = (st.outlineStyle !== 'none' && parseFloat(st.outlineWidth) > 0)
            || st.boxShadow !== 'none' || getComputedStyle(el, ':focus-visible').outlineStyle !== 'none';
          return {sel, hasOutline};
        }""")
        if not info:
            continue
        stops += 1
        seen.append(info["sel"])
        if not info["hasOutline"]:
            no_focus_style += 1
        if info["sel"] == last and len(seen) > 2 and seen[-1] == seen[-2] == seen[-3]:
            trap = True
            break
        last = info["sel"]

    findings: list[dict[str, Any]] = []
    if reachable and stops < reachable * 0.6:
        findings.append({"severity": "medium", "type": "keyboard-unreachable",
                         "detail": f"keyboard reached only {stops} of ~{reachable} interactive elements",
                         "evidence": f"tab stops={stops}, focusable={reachable}"})
    if no_focus_style:
        findings.append({"severity": "medium", "type": "keyboard-focus-invisible",
                         "detail": f"{no_focus_style} focused element(s) show no visible focus indicator",
                         "evidence": "no outline/box-shadow on :focus for these stops"})
    if trap:
        findings.append({"severity": "high", "type": "keyboard-trap",
                         "detail": "focus appears trapped (same element repeats on Tab)",
                         "evidence": f"repeated: {seen[-1] if seen else '?'}"})
    if reachable == 0:
        findings.append({"severity": "low", "type": "keyboard-none",
                         "detail": "no keyboard-focusable interactive elements found", "evidence": "0 focusables"})
    return {"url": url, "focusable": reachable, "tab_stops": stops,
            "no_focus_indicator": no_focus_style, "trap": trap, "findings": findings}


# --------------------------------------------------------------- journey templates
# Scaffolds the AI can copy and fill selectors/values into. Selectors are common
# guesses; the AI should adapt them to the real page after a crawl/snapshot.
JOURNEY_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "login": [
        {"action": "goto", "url": "<login_url>", "label": "open login page"},
        {"action": "fill", "target": "input[type=email],input[name*=user],input[name*=email]", "value": "<email>", "label": "enter username"},
        {"action": "fill", "target": "input[type=password]", "value": "<password>", "label": "enter password"},
        {"action": "click", "target": "button[type=submit],text=Log in,text=Sign in", "label": "submit login"},
        {"action": "assert_url", "target": "<dashboard_path>", "label": "landed on dashboard"},
    ],
    "register": [
        {"action": "goto", "url": "<signup_url>", "label": "open signup"},
        {"action": "fill", "target": "input[name*=name]", "value": "Test User", "label": "enter name"},
        {"action": "fill", "target": "input[type=email]", "value": "<email>", "label": "enter email"},
        {"action": "fill", "target": "input[type=password]", "value": "<password>", "label": "enter password"},
        {"action": "click", "target": "button[type=submit]", "label": "submit signup"},
        {"action": "assert_text", "target": "welcome", "label": "signup succeeded"},
    ],
    "password-reset": [
        {"action": "goto", "url": "<reset_url>", "label": "open reset page"},
        {"action": "fill", "target": "input[type=email]", "value": "<email>", "label": "enter email"},
        {"action": "click", "target": "button[type=submit]", "label": "request reset"},
        {"action": "assert_text", "target": "sent", "label": "reset email confirmed"},
    ],
    "search": [
        {"action": "goto", "url": "<url>", "label": "open site"},
        {"action": "fill", "target": "input[type=search],input[name*=q],input[name*=search]", "value": "<query>", "label": "type query"},
        {"action": "press", "target": "Enter", "label": "submit search"},
        {"action": "assert_text", "target": "<expected_result>", "label": "results shown"},
    ],
    "checkout": [
        {"action": "goto", "url": "<product_url>", "label": "open product"},
        {"action": "click", "target": "text=Add to cart", "label": "add to cart"},
        {"action": "click", "target": "text=Cart,text=Checkout", "label": "go to cart"},
        {"action": "click", "target": "text=Checkout", "label": "start checkout"},
        {"action": "assert_text", "target": "payment", "label": "reached payment step"},
    ],
    "contact": [
        {"action": "goto", "url": "<contact_url>", "label": "open contact page"},
        {"action": "fill", "target": "input[name*=name]", "value": "Test User", "label": "name"},
        {"action": "fill", "target": "input[type=email]", "value": "<email>", "label": "email"},
        {"action": "fill", "target": "textarea", "value": "Hello, this is a test.", "label": "message"},
        {"action": "click", "target": "button[type=submit]", "label": "send"},
        {"action": "assert_text", "target": "thank", "label": "confirmation shown"},
    ],
}


def list_journeys() -> list[str]:
    return list(JOURNEY_TEMPLATES)
