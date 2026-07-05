"""Active form fuzzer — drives real inputs and reads the browser's real verdict.

For each form field we set every relevant test case (valid / invalid / edge /
boundary / out-of-box / injection), then read the browser's OWN judgement via the
Constraint Validation API (``el.validity`` + ``el.validationMessage``) plus any
visible error text. Nothing is faked: a "validation gap" is only reported when
the browser itself said the value was valid where it should have been rejected.

Default is NON-SUBMITTING (client-side validation only). Set ``submit=True`` to
also submit invalid data once and observe server handling — do this only on
targets you are authorized to test and that you don't mind receiving a request.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any

from .browser import manager
from .testdata import cases_for

# JS: for a given field (by index within a form) set a value and report the
# browser's real validity verdict + whether the value is reflected unescaped.
_PROBE_JS = r"""
(args) => {
  const {formIdx, fieldIdx, value, marker} = args;
  const form = document.forms[formIdx];
  if (!form) return {error: 'no form'};
  const el = form.elements[fieldIdx];
  if (!el) return {error: 'no field'};
  const nativeSetter = Object.getOwnPropertyDescriptor(
    el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value');
  try {
    if (nativeSetter && nativeSetter.set) nativeSetter.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
  } catch (e) { return {error: String(e)}; }
  const v = el.validity || {};
  const reflectedRaw = marker ? document.body && document.body.innerHTML.includes('<'+marker) : false;
  return {
    valid: el.checkValidity ? el.checkValidity() : true,
    message: el.validationMessage || '',
    badInput: !!v.badInput, tooLong: !!v.tooLong, typeMismatch: !!v.typeMismatch,
    patternMismatch: !!v.patternMismatch, rangeOverflow: !!v.rangeOverflow,
    valueMissing: !!v.valueMissing,
    maxLength: el.maxLength && el.maxLength > 0 ? el.maxLength : null,
    storedLen: (el.value || '').length,
    reflectedUnescaped: reflectedRaw,
  };
}
"""

_FIELD_META_JS = r"""
() => [...document.forms].map((f, fi) => ({
  idx: fi,
  action: f.getAttribute('action') || location.href,
  method: (f.getAttribute('method') || 'get').toLowerCase(),
  fields: [...f.elements].map((e, i) => ({
    idx: i, name: e.name || e.id || ('field'+i), type: (e.type||'text').toLowerCase(),
    required: !!e.required, tag: e.tagName.toLowerCase(),
    maxLength: e.maxLength && e.maxLength > 0 ? e.maxLength : null,
  })).filter(e => !['hidden','submit','button','reset','image','file','radio',
                    'checkbox','color','select-one','select-multiple'].includes(e.type)),
}))
"""


async def fuzz_forms(url: str, submit: bool = False, max_cases_per_field: int = 40) -> dict[str, Any]:
    """Fuzz every form field with labelled test data; report real validation gaps."""
    page = await manager.page()
    await page.goto(url, wait_until="load", timeout=30000)
    forms = await page.evaluate(_FIELD_META_JS)
    findings: list[dict[str, Any]] = []
    tested = 0
    matrix: list[dict[str, Any]] = []

    for form in forms:
        ftag = f"form#{form['idx']} ({form['method'].upper()} {form['action']})"
        for fld in form["fields"]:
            cases = cases_for(fld["type"], fld["name"])[:max_cases_per_field]
            field_runs: list[dict[str, Any]] = []
            for case in cases:
                marker = "fagunX" if case.category == "injection" else ""
                try:
                    res = await page.evaluate(_PROBE_JS, {
                        "formIdx": form["idx"], "fieldIdx": fld["idx"],
                        "value": case.value, "marker": marker,
                    })
                except Exception:
                    continue
                if res.get("error"):
                    continue
                tested += 1
                verdict = {
                    "category": case.category,
                    "label": case.label,
                    "expect": case.expect or "observe",
                    "browser_valid": bool(res.get("valid", True)),
                    "message": res.get("message", ""),
                    "stored_len": res.get("storedLen"),
                }
                field_runs.append(verdict)
                new_findings = _judge(ftag, fld, case, res)
                if new_findings:
                    shot = await _capture_evidence(page, f"form-{form['idx']}-{fld['idx']}-{case.category}")
                    for f in new_findings:
                        if shot:
                            f["screenshot"] = shot
                            f.setdefault("evidence", "")
                            f["evidence"] = (f["evidence"] + f"; screenshot: {shot}").strip("; ")
                    findings.extend(new_findings)
            matrix.append({
                "form": ftag,
                "field": fld["name"],
                "type": fld["type"],
                "required": fld.get("required", False),
                "cases": field_runs,
                "summary": _matrix_summary(field_runs),
            })

        if submit:
            findings.extend(await _submit_probe(page, form, ftag))

    # Dedup by (type, detail).
    seen: set[tuple[str, str]] = set()
    uniq = []
    for f in findings:
        k = (f["type"], f["detail"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return {"url": url, "forms": len(forms), "cases_tested": tested,
            "scenario_matrix": matrix, "findings": uniq}


async def _capture_evidence(page, tag: str) -> str | None:
    try:
        safe = "".join(c for c in tag if c.isalnum() or c in "-_")[:40] or "form"
        path = os.path.join(tempfile.gettempdir(), f"fagun-{safe}-{int(time.time()*1000) % 10**7}.png")
        await page.screenshot(path=path)
        return path
    except Exception:
        return None


def _matrix_summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    out = {"total": len(cases), "valid": 0, "invalid": 0, "accepted_reject_cases": 0}
    for c in cases:
        if c.get("browser_valid"):
            out["valid"] += 1
            if c.get("expect") == "reject":
                out["accepted_reject_cases"] += 1
        else:
            out["invalid"] += 1
    return out


def _judge(ftag: str, fld: dict, case, res: dict) -> list[dict[str, Any]]:
    """Turn one real probe result into findings. Only reports observed facts."""
    out = []
    name = fld["name"]
    browser_valid = res.get("valid", True)

    # 1. Injection reflected unescaped in the DOM = client-side/DOM-XSS signal.
    if case.category == "injection" and res.get("reflectedUnescaped"):
        out.append({"severity": "high", "type": "form-xss",
                    "detail": f"{ftag} field {name!r}: injected markup reflected unescaped into DOM",
                    "evidence": f"case '{case.label}' produced unescaped '<fagunX' in page HTML"})

    # 2. Value that SHOULD be rejected but the browser accepts (validation gap).
    if case.expect == "reject" and browser_valid:
        # Only meaningful if the field has *some* constraint (type/required/pattern);
        # a plain text field legitimately accepts anything — don't cry wolf.
        constrained = fld["type"] not in ("text", "search", "textarea") or fld["required"]
        if constrained:
            sev = "medium" if case.category == "invalid" else "low"
            out.append({"severity": sev, "type": "form-validation-gap",
                        "detail": f"{ftag} field {name!r} accepts {case.category} value ({case.label})",
                        "evidence": f"browser checkValidity()=true for value {_clip(case.value)!r}"})

    # 3. Length: field stored an over-limit string despite a maxLength.
    ml = res.get("maxLength")
    if ml and res.get("storedLen", 0) > ml:
        out.append({"severity": "low", "type": "form-maxlength",
                    "detail": f"{ftag} field {name!r} stored {res['storedLen']} chars past maxLength={ml}",
                    "evidence": f"case '{case.label}'"})

    # 4. Boundary overflow with no maxLength at all (DoS / storage risk surface).
    if case.category == "boundary" and "overflow" in case.label and not ml and browser_valid:
        out.append({"severity": "low", "type": "form-no-maxlength",
                    "detail": f"{ftag} field {name!r} has no maxLength — accepts 5000-char input",
                    "evidence": "boundary case accepted with no length cap"})
    return out


async def _submit_probe(page, form, ftag) -> list[dict[str, Any]]:
    """Submit the form once with an injection marker and watch for 5xx/errors.
    Non-idempotent — only runs when submit=True."""
    out = []
    manager.clear_logs()
    try:
        # Fill first text-ish field with an injection marker, then submit.
        await page.evaluate(
            """(fi) => {
                const f = document.forms[fi]; if (!f) return;
                for (const e of f.elements) {
                    if (['text','search','email','url','textarea'].includes((e.type||'').toLowerCase())) {
                        e.value = "fagunSUB'\\"><b>"; e.dispatchEvent(new Event('input',{bubbles:true})); break;
                    }
                }
                if (f.requestSubmit) f.requestSubmit(); else f.submit();
            }""", form["idx"])
        await page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
    for n in manager.network:
        if n.status and n.status >= 500:
            out.append({"severity": "high", "type": "form-server-error",
                        "detail": f"{ftag} submit triggered {n.status} — server error on crafted input",
                        "evidence": f"{n.method} {n.url} → {n.status}"})
    return out


def _clip(s: str, n: int = 30) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
