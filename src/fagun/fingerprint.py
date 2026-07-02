"""Tech-stack fingerprint — know what you're testing before you test it.

Reads real signals only: response headers, meta[generator], global JS objects,
and script/link sources on the rendered page. No guessing — every hit maps to an
observed marker. Knowing the stack lets the AI tune its hunt (e.g. WordPress →
check xmlrpc/wp-json; Next.js → check /_next/data; nginx version → CVE lookup)
and gives the report useful context.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .browser import manager

# window-global / DOM markers evaluated in the page. (label, JS expression → bool)
_JS_PROBE = r"""
() => {
  const has = {};
  const w = window, d = document;
  const html = d.documentElement.outerHTML;
  const gen = (d.querySelector('meta[name="generator"]')||{}).content || '';
  has['React'] = !!(w.React || d.querySelector('[data-reactroot],#__next') || w.__NEXT_DATA__);
  has['Next.js'] = !!(w.__NEXT_DATA__ || d.querySelector('script[src*="/_next/"]'));
  has['Vue'] = !!(w.Vue || d.querySelector('[data-v-app],#app[data-v-]'));
  has['Nuxt'] = !!(w.__NUXT__ || w.$nuxt);
  has['Angular'] = !!(w.ng || d.querySelector('[ng-version]'));
  has['Svelte'] = !!(d.querySelector('style[data-svelte],[class*="svelte-"]'));
  has['jQuery'] = !!(w.jQuery || w.$ && w.$.fn && w.$.fn.jquery);
  has['WordPress'] = /wp-content|wp-includes/.test(html) || /WordPress/i.test(gen);
  has['Drupal'] = !!w.Drupal || /Drupal/i.test(gen);
  has['Shopify'] = !!w.Shopify || /cdn\.shopify\.com/.test(html);
  has['Wix'] = /Wix\.com|static\.wixstatic/.test(html) || /Wix/i.test(gen);
  has['Squarespace'] = /squarespace/i.test(html) || /Squarespace/i.test(gen);
  has['Google Analytics'] = !!(w.ga || w.gtag || w.google_tag_manager);
  has['Google Tag Manager'] = !!w.dataLayer && /googletagmanager/.test(html);
  has['Segment'] = !!w.analytics && !!w.analytics.Integrations;
  has['Sentry'] = !!(w.Sentry || w.__SENTRY__);
  has['Stripe'] = !!w.Stripe || /js\.stripe\.com/.test(html);
  has['Cloudflare (turnstile)'] = /challenges\.cloudflare\.com|turnstile/.test(html);
  has['reCAPTCHA'] = !!w.grecaptcha || /recaptcha/.test(html);
  has['Bootstrap'] = !!(w.bootstrap) || /bootstrap(\.min)?\.(css|js)/.test(html);
  has['Tailwind'] = /tailwind/i.test(html) || !!d.querySelector('[class~="flex"][class~="items-center"]');
  return {markers: Object.keys(has).filter(k => has[k]), generator: gen};
}
"""

# Server/proxy/framework signals from response headers.
_HEADER_KEYS = ["server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version",
                "via", "x-generator", "x-drupal-cache", "x-shopify-stage",
                "x-vercel-id", "x-nf-request-id", "cf-ray", "x-served-by",
                "x-fastcgi-cache", "x-litespeed-cache"]

_VENDOR_HEADERS = {
    "x-vercel-id": "Vercel", "x-nf-request-id": "Netlify", "cf-ray": "Cloudflare",
    "x-drupal-cache": "Drupal", "x-shopify-stage": "Shopify",
    "x-litespeed-cache": "LiteSpeed", "x-fastcgi-cache": "Nginx FastCGI cache",
}


async def fingerprint(url: str) -> dict[str, Any]:
    """Detect server, frameworks, analytics, and platform for a URL."""
    page = await manager.page()
    tech: dict[str, Any] = {"server": None, "powered_by": None, "hosting": [],
                            "frameworks": [], "analytics": [], "generator": None,
                            "headers": {}}

    # Headers (own request so we get the raw response headers).
    try:
        r = await page.request.get(url, timeout=15000, fail_on_status_code=False)
        h = {k.lower(): v for k, v in r.headers.items()}
        tech["server"] = h.get("server")
        tech["powered_by"] = h.get("x-powered-by")
        tech["headers"] = {k: h[k] for k in _HEADER_KEYS if k in h}
        for hk, vendor in _VENDOR_HEADERS.items():
            if hk in h and vendor not in tech["hosting"]:
                tech["hosting"].append(vendor)
    except Exception:
        pass

    # DOM / JS globals on the rendered page.
    try:
        await page.goto(url, wait_until="load", timeout=30000)
        data = await page.evaluate(_JS_PROBE)
        analytics_labels = {"Google Analytics", "Google Tag Manager", "Segment", "Sentry"}
        for m in data.get("markers", []):
            (tech["analytics"] if m in analytics_labels else tech["frameworks"]).append(m)
        tech["generator"] = data.get("generator") or None
    except Exception:
        pass

    summary = _summarize(tech)
    return {"url": url, "tech": tech, "summary": summary,
            "findings": _findings(url, tech)}


def _summarize(t: dict[str, Any]) -> str:
    bits = []
    if t.get("server"):
        bits.append(f"server={t['server']}")
    if t.get("powered_by"):
        bits.append(f"x-powered-by={t['powered_by']}")
    if t.get("hosting"):
        bits.append("hosting=" + "/".join(t["hosting"]))
    if t.get("frameworks"):
        bits.append("stack=" + ", ".join(t["frameworks"]))
    if t.get("analytics"):
        bits.append("analytics=" + ", ".join(t["analytics"]))
    if t.get("generator"):
        bits.append(f"generator={t['generator']}")
    return " | ".join(bits) or "no strong tech signals detected"


def _findings(url: str, t: dict[str, Any]) -> list[dict[str, Any]]:
    """Only surfaces things that matter for hardening — e.g. a version-leaking
    Server header. The stack itself is informational, returned in `tech`."""
    out = []
    server = (t.get("server") or "")
    if server and any(c.isdigit() for c in server):
        out.append({"severity": "low", "type": "info-leak",
                    "detail": f"Server header leaks version: {server}",
                    "evidence": f"Server: {server}"})
    if t.get("powered_by"):
        out.append({"severity": "low", "type": "info-leak",
                    "detail": f"X-Powered-By leaks stack: {t['powered_by']}",
                    "evidence": f"X-Powered-By: {t['powered_by']}"})
    return out
