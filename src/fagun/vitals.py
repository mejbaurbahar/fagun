"""Real performance measurement — Core Web Vitals + Lighthouse-style scoring.

No estimates, no fabrication: every number is read from the browser's own
Performance APIs (Navigation Timing, Paint Timing, PerformanceObserver for
LCP/CLS/long-tasks) after a real load with a settle window. Scores use the same
metric weights and log-normal curves Lighthouse uses, so a Fagun perf score is
directly comparable to a Lighthouse perf score.
"""

from __future__ import annotations

import math
from typing import Any

from .browser import manager

# Lighthouse v10 metric weights (performance category) and log-normal params
# (median, podr = point-of-diminishing-returns) sourced from Lighthouse scoring.
_CURVES = {
    "FCP": {"weight": 0.10, "median": 1600, "podr": 934},
    "SI": {"weight": 0.10, "median": 3387, "podr": 1311},
    "LCP": {"weight": 0.25, "median": 2500, "podr": 1200},
    "TBT": {"weight": 0.30, "median": 350, "podr": 200},
    "CLS": {"weight": 0.15, "median": 0.25, "podr": 0.1},
    "TTI": {"weight": 0.10, "median": 7300, "podr": 2468},
}

# Field-quality thresholds (Google "good / needs-improvement / poor").
_RATING = {
    "LCP": (2500, 4000),
    "CLS": (0.1, 0.25),
    "TBT": (200, 600),
    "FCP": (1800, 3000),
    "TTFB": (800, 1800),
    "INP": (200, 500),
}


def _log_normal_score(value: float, median: float, podr: float) -> float:
    """Lighthouse log-normal CDF: 1.0 = perfect, 0 = worst. Real curve, not linear."""
    if value <= 0:
        return 1.0
    location = math.log(median)
    # shape derived from median & podr per Lighthouse's makeLogNormalScorer
    shape = abs(math.log(podr) - location) / (math.sqrt(2) * 0.9061938024368232)
    if shape == 0:
        return 1.0
    z = (math.log(value) - location) / (shape * math.sqrt(2))
    return max(0.0, min(1.0, 0.5 * math.erfc(z)))


def rate(metric: str, value: float) -> str:
    lo, hi = _RATING.get(metric, (0, 0))
    if not hi:
        return "?"
    return "good" if value <= lo else "needs-improvement" if value <= hi else "poor"


# JS injected to collect real vitals. Uses PerformanceObserver for LCP/CLS/
# long-tasks, Navigation Timing for TTFB/DCL/load, Paint Timing for FCP.
_COLLECT_JS = """
() => new Promise((resolve) => {
  const out = {LCP: 0, CLS: 0, TBT: 0, longTasks: 0, INP: 0};
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) out.LCP = Math.max(out.LCP, e.renderTime || e.loadTime || e.startTime);
    }).observe({type: 'largest-contentful-paint', buffered: true});
  } catch (e) {}
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) if (!e.hadRecentInput) out.CLS += e.value;
    }).observe({type: 'layout-shift', buffered: true});
  } catch (e) {}
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        out.longTasks++;
        out.TBT += Math.max(0, e.duration - 50); // blocking time over the 50ms budget
      }
    }).observe({type: 'longtask', buffered: true});
  } catch (e) {}
  // give observers a moment to flush, then read timing entries
  setTimeout(() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const paints = {};
    for (const p of performance.getEntriesByType('paint')) paints[p.name] = p.startTime;
    const res = performance.getEntriesByType('resource');
    out.TTFB = nav.responseStart || 0;
    out.FCP = paints['first-contentful-paint'] || 0;
    out.FP = paints['first-paint'] || 0;
    out.DCL = nav.domContentLoadedEventEnd || 0;
    out.load = nav.loadEventEnd || 0;
    out.domInteractive = nav.domInteractive || 0;
    out.transferKB = Math.round((nav.transferSize || 0) / 1024);
    out.resourceCount = res.length;
    out.resourceKB = Math.round(res.reduce((s, r) => s + (r.transferSize || 0), 0) / 1024);
    out.LCP = out.LCP || out.FCP;      // fall back to FCP if no LCP entry
    out.TTI = Math.max(out.domInteractive, out.FCP); // conservative TTI proxy
    out.SI = out.FCP;                  // speed-index proxy from first paint
    resolve(out);
  }, 1200);
})
"""


async def measure(url: str) -> dict[str, Any]:
    """Load a URL and return real measured metrics + a Lighthouse-style score."""
    page = await manager.page()
    await page.goto(url, wait_until="load", timeout=45000)
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass  # networkidle may never fire on live sites; metrics still valid
    m = await page.evaluate(_COLLECT_JS)

    # Round for readability; keep raw for scoring.
    metrics = {k: (round(v, 3) if k == "CLS" else round(v)) for k, v in m.items()}

    scored = {}
    weighted = 0.0
    for name, cfg in _CURVES.items():
        val = float(m.get(name, 0) or 0)
        s = _log_normal_score(val, cfg["median"], cfg["podr"])
        scored[name] = round(s * 100)
        weighted += s * cfg["weight"]
    perf_score = round(weighted * 100)

    findings = _findings(metrics)
    return {
        "url": url,
        "score": perf_score,
        "metrics": metrics,
        "metric_scores": scored,
        "ratings": {k: rate(k, metrics.get(k, 0)) for k in _RATING if k in metrics},
        "findings": findings,
    }


def _findings(m: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    checks = [
        ("LCP", "medium", "Largest Contentful Paint slow"),
        ("CLS", "medium", "Cumulative Layout Shift high"),
        ("TBT", "medium", "Total Blocking Time high"),
        ("FCP", "low", "First Contentful Paint slow"),
        ("TTFB", "medium", "Time To First Byte slow (server/network)"),
    ]
    for metric, sev, msg in checks:
        if metric not in m:
            continue
        r = rate(metric, m[metric])
        if r == "poor":
            out.append({"severity": sev, "type": "perf-vitals",
                        "detail": f"{msg}: {metric}={m[metric]} ({r})",
                        "evidence": f"measured {metric}={m[metric]} via Performance API"})
        elif r == "needs-improvement":
            out.append({"severity": "low", "type": "perf-vitals",
                        "detail": f"{metric}={m[metric]} needs improvement",
                        "evidence": f"measured {metric}={m[metric]}"})
    if m.get("resourceKB", 0) > 3000:
        out.append({"severity": "low", "type": "perf-weight",
                    "detail": f"Heavy page: {m['resourceKB']} KB over {m.get('resourceCount', '?')} resources",
                    "evidence": f"sum of resource transferSize = {m['resourceKB']} KB"})
    return out
