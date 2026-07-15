"""Product-readiness scorecard — turn raw findings into a release decision.

Aggregates every finding Fagun collected (QA, a11y, perf, security, forms,
journeys, keyboard, personas) into per-category scores (0-100), an overall
verdict, and a prioritized, actionable improvement list. Scores are derived
purely from the evidence gathered — a category only loses points for findings
that actually map to it, and every deduction is traceable.

This is deliberately transparent, not a black box: the AI (and the user) can see
exactly which findings drove each score.
"""

from __future__ import annotations

from typing import Any

# 16 readiness dimensions the user cares about.
CATEGORIES = [
    "UX", "UI", "Business Logic", "Reliability", "Stability", "Accessibility",
    "Performance", "Security", "Mobile", "Desktop", "API", "Documentation",
    "Discoverability", "Learnability", "Customer Satisfaction", "Production Readiness",
]

# finding "type" (prefix match) -> categories it affects.
_TYPE_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("a11y-", ("Accessibility",)),
    ("keyboard-", ("Accessibility", "UX")),
    ("console-error", ("Reliability", "Stability")),
    ("console-warning", ("Stability",)),
    ("request-failed", ("Reliability", "Stability")),
    ("bad-response", ("Reliability", "API")),
    ("load-failure", ("Reliability", "Stability")),
    ("http-error", ("Reliability",)),
    ("broken-link", ("Reliability", "UX")),
    ("perf", ("Performance",)),
    ("vitals-", ("Performance",)),
    ("seo", ("Discoverability",)),
    ("form-a11y", ("Accessibility", "UX")),
    ("form-validation", ("Business Logic", "UX")),
    ("form-hint", ("UX",)),
    ("form-security", ("Security",)),
    ("form-xss", ("Security",)),
    ("form-server-error", ("Reliability", "Business Logic")),
    ("form-maxlength", ("Business Logic",)),
    ("form-no-maxlength", ("Business Logic",)),
    ("journey-blocked", ("Business Logic", "Reliability", "Customer Satisfaction")),
    ("journey-console-error", ("Reliability", "Stability")),
    ("journey-request-failed", ("Reliability", "API")),
    ("journey-slow", ("Performance", "Customer Satisfaction")),
    ("sec-header", ("Security",)),
    ("info-leak", ("Security",)),
    ("exposed-file", ("Security",)),
    ("leaked-secret", ("Security",)),
    ("cors", ("Security", "API")),
    ("cookie-flags", ("Security",)),
    ("xss", ("Security",)),
    ("reflection", ("Security",)),
    ("open-redirect", ("Security",)),
    ("sqli", ("Security",)),
    ("csp", ("Security",)),
    ("clickjacking", ("Security",)),
    ("http-methods", ("Security",)),
    ("mixed-content", ("Security",)),
    ("missing-sri", ("Security",)),
    ("cache-sensitive", ("Security",)),
    ("host-header", ("Security",)),
    ("crlf", ("Security",)),
    ("path-traversal", ("Security",)),
    ("ssti", ("Security",)),
    ("command-injection", ("Security",)),
    ("graphql", ("Security", "API")),
    ("error-disclosure", ("Security",)),
    ("sensitive-in-url", ("Security",)),
]

_WEIGHT = {"high": 22, "medium": 9, "low": 3}

# Actionable advice per finding-type prefix (why it matters + how to fix).
_ADVICE: list[tuple[str, str, str]] = [
    ("journey-blocked", "A core user journey cannot be completed — direct revenue/adoption loss.",
     "Fix the broken step so the flow works end-to-end; add a regression test for it."),
    ("a11y-inputLabel", "Screen-reader and voice users cannot identify form fields.",
     "Add <label for>, aria-label, or wrap the control in a <label>."),
    ("a11y-emptyControl", "Buttons/links with no text are unusable for assistive tech.",
     "Give every control discernible text or an aria-label."),
    ("a11y-contrast", "Low-contrast text is unreadable for low-vision and mobile-in-sunlight users.",
     "Raise contrast to WCAG AA (4.5:1 body / 3:1 large text)."),
    ("keyboard-trap", "Keyboard users get stuck and cannot leave the component.",
     "Ensure Tab/Shift+Tab and Escape move focus out; test the full tab order."),
    ("keyboard-focus-invisible", "Keyboard users can't see where they are on the page.",
     "Provide a visible :focus-visible outline on all interactive elements."),
    ("leaked-secret", "A live credential is exposed — immediate compromise risk.",
     "Rotate the key now and remove it from client-delivered code."),
    ("exposed-file", "Sensitive server files are publicly reachable.",
     "Block these paths at the web server / deny access and remove the files."),
    ("sqli", "Database is likely injectable — data breach risk.",
     "Use parameterized queries; never build SQL from user input."),
    ("ssti", "Template injection can lead to RCE.",
     "Never render user input as a template; sanitize and use safe contexts."),
    ("xss", "Reflected input enables account/session theft.",
     "Contextually escape output and set a strict CSP."),
    ("form-security", "Credentials/data submitted insecurely.",
     "POST over HTTPS only; never send passwords via GET."),
    ("sec-header", "Missing hardening headers widen the attack surface.",
     "Add CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy."),
    ("perf", "Slow loads increase bounce and hurt conversion.",
     "Optimize the critical path: compress, lazy-load, cache, cut blocking JS."),
    ("vitals-", "Poor Core Web Vitals harm UX and SEO ranking.",
     "Fix LCP/CLS/TBT: size images, reserve layout space, defer heavy scripts."),
    ("broken-link", "Dead links break navigation and erode trust.",
     "Fix or remove the broken targets; add link-checking to CI."),
    ("seo", "Weak metadata reduces search discoverability.",
     "Add title/description/canonical/viewport and a single <h1>."),
    ("form-validation", "Weak client validation frustrates users and lets bad data through.",
     "Mark required fields; validate types; give inline, specific errors."),
]


def _categorize(ftype: str) -> tuple[str, ...]:
    for prefix, cats in _TYPE_MAP:
        if ftype.startswith(prefix):
            return cats
    return ("Reliability",)  # unknown findings default to reliability signal


def build_scorecard(results: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute category scores + verdict + recommendations from collected results.

    ``results`` is a list of per-page/per-check dicts each with a ``findings``
    list (the same shape QA/security/uat tools already return). ``meta`` can
    carry extra signals like {"journeys": [...], "personas_tested": [...]}.
    """
    meta = meta or {}
    all_findings: list[dict[str, Any]] = []
    for r in results:
        for f in r.get("findings", []):
            g = dict(f)
            g.setdefault("url", r.get("url", "?"))
            all_findings.append(g)

    scores = {c: 100.0 for c in CATEGORIES}
    hits: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for f in all_findings:
        sev = f.get("severity", "low")
        w = _WEIGHT.get(sev, 3)
        for cat in _categorize(f.get("type", "")):
            scores[cat] = max(0.0, scores[cat] * (1.0 - w / 130.0))
            hits[cat].append(f)

    # Production Readiness = weighted floor of the rest (worst areas dominate).
    core = [scores[c] for c in CATEGORIES if c != "Production Readiness"]
    lowest = min(core) if core else 100.0
    avg = sum(core) / len(core) if core else 100.0
    scores["Production Readiness"] = round(0.6 * lowest + 0.4 * avg, 1)

    sev_counts = {"high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev_counts[f.get("severity", "low")] = sev_counts.get(f.get("severity", "low"), 0) + 1

    sec_high = sum(1 for f in all_findings
                   if f.get("severity") == "high" and "Security" in _categorize(f.get("type", "")))
    blocked = sum(1 for f in all_findings if f.get("type", "").startswith("journey-blocked"))

    overall = scores["Production Readiness"]
    verdict, reason = _verdict(overall, sev_counts, sec_high, blocked, meta)

    return {
        "overall_score": round(overall, 1),
        "verdict": verdict,
        "verdict_reason": reason,
        "severity_counts": sev_counts,
        "categories": {c: {"score": round(scores[c], 1), "findings": len(hits[c])} for c in CATEGORIES},
        "recommendations": _recommend(all_findings),
        "meta": meta,
        "total_findings": len(all_findings),
    }


def _verdict(overall: float, sev: dict[str, int], sec_high: int, blocked: int,
             meta: dict[str, Any]) -> tuple[str, str]:
    if sec_high >= 2 or blocked >= 2 or (sec_high and blocked):
        return ("Critical Issues Block Release",
                f"{sec_high} high-severity security issue(s) and {blocked} blocked journey(s).")
    if sec_high == 1 or blocked == 1 or overall < 45:
        return ("Not Ready for Production",
                f"{sec_high} security-critical, {blocked} blocked journey, overall {overall:.0f}/100.")
    if sev["high"] > 0 or overall < 65:
        return ("Ready After Fixing Medium-Priority Issues",
                f"{sev['high']} high / {sev['medium']} medium findings to resolve first.")
    if sev["medium"] > 0 or overall < 88:
        return ("Ready with Minor Improvements",
                f"No blockers; {sev['medium']} medium and {sev['low']} low polish items remain.")
    return ("Ready for Production", f"No blocking issues; overall {overall:.0f}/100.")


def _advice_for(ftype: str) -> tuple[str, str] | None:
    for prefix, why, fix in _ADVICE:
        if ftype.startswith(prefix):
            return why, fix
    return None


def _recommend(findings: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Prioritized, de-duplicated recommendations: highest severity first."""
    order = {"high": 0, "medium": 1, "low": 2}
    # group by type, keep worst severity + count
    grouped: dict[str, dict[str, Any]] = {}
    for f in findings:
        t = f.get("type", "other")
        g = grouped.setdefault(t, {"type": t, "severity": f.get("severity", "low"),
                                    "count": 0, "example": f.get("detail", "")})
        g["count"] += 1
        if order.get(f.get("severity", "low"), 3) < order.get(g["severity"], 3):
            g["severity"] = f.get("severity", "low")
            g["example"] = f.get("detail", "")
    recs = []
    for g in sorted(grouped.values(), key=lambda x: (order.get(x["severity"], 3), -x["count"])):
        adv = _advice_for(g["type"])
        recs.append({
            "severity": g["severity"], "type": g["type"], "count": g["count"],
            "issue": g["example"],
            "why": adv[0] if adv else "Affects the end-user experience or trust.",
            "fix": adv[1] if adv else "Review and resolve; confirm the fix with a re-test.",
        })
    return recs[:limit]
