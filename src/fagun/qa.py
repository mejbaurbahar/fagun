"""QA engine — crawl a site and run an automated bug/quality sweep.

Findings are plain dicts so they serialize cleanly back to the AI tool and into
the report writer.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from . import a11y as _a11y
from . import advsec as _advsec
from . import vitals as _vitals
from .browser import manager
from .forms import fuzz_forms as _fuzz_forms


def _same_site(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_SITEMAP_RE = re.compile(r"(?im)^\s*sitemap:\s*(\S+)")


async def _seed_from_sitemap(start_url: str, max_urls: int = 500) -> list[str]:
    """Discover same-site URLs from robots.txt (Sitemap: lines) and /sitemap.xml.
    Surfaces pages not linked from the homepage. Best-effort — returns [] on any
    error. Follows two levels of sitemap-index nesting to catch deep sitemaps."""
    p = urlparse(start_url)
    root = f"{p.scheme}://{p.netloc}"
    page = await manager.page()

    async def _fetch(u: str) -> str:
        try:
            r = await page.request.get(u, timeout=12000, fail_on_status_code=False)
            return (await r.text())[:1000000] if r.status == 200 else ""
        except Exception:
            return ""

    sitemaps: list[str] = []
    robots = await _fetch(root + "/robots.txt")
    sitemaps += _SITEMAP_RE.findall(robots)
    # Common sitemap locations
    for candidate in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                      "/sitemaps/sitemap.xml", "/wp-sitemap.xml", "/news-sitemap.xml"]:
        sitemaps.append(root + candidate)

    found: list[str] = []
    seen_sm: set[str] = set()
    for sm in sitemaps[:10]:
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        body = await _fetch(sm)
        locs = _LOC_RE.findall(body)
        # Sitemap index: follow two levels of nested sitemaps
        nested_l1 = [l for l in locs if l.rstrip("/").endswith(".xml")]
        for n in nested_l1[:10]:
            if n not in seen_sm:
                seen_sm.add(n)
                body2 = await _fetch(n)
                locs2 = _LOC_RE.findall(body2)
                nested_l2 = [l for l in locs2 if l.rstrip("/").endswith(".xml")]
                for n2 in nested_l2[:5]:
                    if n2 not in seen_sm:
                        seen_sm.add(n2)
                        locs2 += _LOC_RE.findall(await _fetch(n2))
                locs += locs2
        for loc in locs:
            loc = urldefrag(loc)[0]
            if loc.endswith(".xml"):
                continue
            if _same_site(start_url, loc) and loc not in found:
                found.append(loc)
            if len(found) >= max_urls:
                return found
    return found


async def _seed_from_spa_routes(start_url: str) -> list[str]:
    """Extract client-side routes from SPA frameworks (Next.js, Nuxt, React Router,
    Vue Router, Angular). Catches pages not linked from the DOM at load time."""
    page = await manager.page()
    _p = urlparse(start_url)
    root = f"{_p.scheme}://{_p.netloc}"  # noqa: F841 — kept for clarity
    try:
        await page.goto(start_url, wait_until="networkidle", timeout=30000)
    except Exception:
        return []

    try:
        routes = await page.evaluate(
            """() => {
                const routes = new Set();
                const origin = location.origin;

                // Next.js: __NEXT_DATA__ build manifest
                try {
                    const nd = window.__NEXT_DATA__;
                    if (nd && nd.buildId) {
                        const manifestUrl = `${origin}/_next/static/${nd.buildId}/_buildManifest.js`;
                        // can't fetch sync; record sitemap-style hrefs we can see
                    }
                    if (nd && nd.page) routes.add(nd.page);
                    // pages-manifest in SSG
                    if (nd && nd.props && nd.props.pageProps) {
                        const paths = nd.props.pageProps.__N_SSP || nd.props.pageProps.__N_SSG || [];
                        paths.forEach && paths.forEach(p => routes.add(p));
                    }
                } catch(e){}

                // Nuxt.js
                try {
                    const nc = window.__NUXT__;
                    if (nc && nc.routePath) routes.add(nc.routePath);
                } catch(e){}

                // React Router / Vue Router: scan all <a> including client-rendered
                document.querySelectorAll('a[href]').forEach(a => {
                    try {
                        const u = new URL(a.href, location.href);
                        if (u.origin === origin && !u.pathname.match(/\\.(?:js|css|png|jpg|gif|svg|ico|woff|ttf|map)$/)) {
                            routes.add(u.pathname + u.search);
                        }
                    } catch(e){}
                });

                // Angular router outlet links & data-routerlink
                document.querySelectorAll('[routerlink],[data-routerlink],[ng-href]').forEach(el => {
                    const r = el.getAttribute('routerlink') || el.getAttribute('data-routerlink') || el.getAttribute('ng-href');
                    if (r && r.startsWith('/')) routes.add(r);
                });

                // data-href, data-url, data-to attributes (various frameworks)
                document.querySelectorAll('[data-href],[data-url],[data-to]').forEach(el => {
                    const r = el.getAttribute('data-href') || el.getAttribute('data-url') || el.getAttribute('data-to');
                    if (r && (r.startsWith('/') || r.startsWith(origin))) {
                        try { routes.add(new URL(r, location.href).pathname); } catch(e){}
                    }
                });

                // Next.js Link elements (rendered as <a> but catch data-* too)
                // Scan nav/menu/sidebar/footer for ALL links including JS-driven menus
                const navSelectors = 'nav a, header a, footer a, [role="navigation"] a, [aria-label*="nav" i] a, .sidebar a, .menu a, .drawer a, aside a';
                document.querySelectorAll(navSelectors).forEach(a => {
                    try {
                        const u = new URL(a.href, location.href);
                        if (u.origin === origin) routes.add(u.pathname + u.search);
                    } catch(e){}
                });

                return [...routes].filter(r => r && r !== '/').slice(0, 300);
            }"""
        )
        p_parsed = urlparse(start_url)
        root_real = f"{p_parsed.scheme}://{p_parsed.netloc}"
        found = []
        for r in (routes or []):
            if r.startswith("http"):
                abs_url = urldefrag(r)[0]
            else:
                abs_url = urldefrag(root_real + r)[0]
            if _same_site(start_url, abs_url):
                found.append(abs_url)
        return found
    except Exception:
        return []


async def _seed_from_nav_links(start_url: str) -> list[str]:
    """Harvest all navigation, sidebar, footer, and menu links from the loaded page.
    Ensures top-level sections not in sitemap are still discovered."""
    page = await manager.page()
    p_parsed = urlparse(start_url)
    root = f"{p_parsed.scheme}://{p_parsed.netloc}"
    found = []
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]", "els => [...new Set(els.map(e => e.href))]"
        )
        for h in hrefs:
            if not h or not h.startswith("http"):
                continue
            abs_url = urldefrag(h)[0]
            if _same_site(start_url, abs_url):
                found.append(abs_url)
    except Exception:
        pass
    return found


async def crawl(start_url: str, max_pages: int = 50) -> dict[str, Any]:
    """Breadth-first crawl within the same host. Seeded from four sources so that
    unlinked pages, SPA routes, and sitemap-only pages are all discovered:
    1. sitemap.xml / robots.txt (including nested sitemap-index)
    2. SPA framework routes (Next.js, Nuxt, React Router, Angular, Vue)
    3. All navigation/sidebar/footer/menu links on the homepage
    4. BFS link-following during the crawl itself
    Returns all discovered pages up to max_pages."""
    page = await manager.page()
    seen: set[str] = set()
    start = urldefrag(start_url)[0]

    # Seed phase: collect candidate URLs from all discovery methods before BFS.
    seed_urls: list[str] = [start]

    # 1. Sitemap / robots.txt
    try:
        for u in await _seed_from_sitemap(start_url):
            if u not in seen and u not in seed_urls:
                seed_urls.append(u)
    except Exception:
        pass

    # 2. SPA routes (loads the page once for JS route discovery)
    try:
        for u in await _seed_from_spa_routes(start_url):
            if u not in seen and u not in seed_urls:
                seed_urls.append(u)
    except Exception:
        pass

    # 3. Nav/sidebar/footer links from homepage (already loaded above)
    try:
        for u in await _seed_from_nav_links(start_url):
            if u not in seen and u not in seed_urls:
                seed_urls.append(u)
    except Exception:
        pass

    queue: list[str] = seed_urls
    pages: list[dict[str, Any]] = []

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status = resp.status if resp else None
            title = await page.title()
        except Exception as e:
            pages.append({"url": url, "status": None, "error": str(e)})
            continue

        # BFS: discover more links from each visited page
        hrefs = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
        links = []
        for h in hrefs:
            if not h or h.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urldefrag(urljoin(url, h))[0]
            links.append(absolute)
            if _same_site(start_url, absolute) and absolute not in seen:
                queue.append(absolute)

        pages.append(
            {"url": url, "status": status, "title": title, "links_found": len(links)}
        )

    return {
        "start": start_url,
        "crawled": len(pages),
        "pages": pages,
        "seed_sources": ["sitemap/robots", "spa-routes", "nav-links", "bfs"],
    }


async def _seo_checks(page) -> list[dict[str, Any]]:
    """Real SEO/meta signals read from the loaded document — core, OG, Twitter, JSON-LD."""
    data = await page.evaluate(
        """() => {
            const g = (s, a='content') => { const e = document.querySelector(s); return e ? (e.getAttribute(a)||'') : null; };
            const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.textContent); } catch(_) { return null; } })
                .filter(Boolean);
            return {
                title: (document.title||'').trim(),
                desc: g('meta[name="description"]'),
                canonical: g('link[rel="canonical"]','href'),
                robots: g('meta[name="robots"]'),
                viewport: g('meta[name="viewport"]'),
                h1: document.querySelectorAll('h1').length,
                ogTitle: g('meta[property="og:title"]'),
                ogDesc: g('meta[property="og:description"]'),
                ogImage: g('meta[property="og:image"]'),
                ogType: g('meta[property="og:type"]'),
                twCard: g('meta[name="twitter:card"]'),
                twTitle: g('meta[name="twitter:title"]'),
                jsonLdCount: jsonLd.length,
                jsonLdTypes: jsonLd.map(j => j['@type'] || '').filter(Boolean).slice(0,5),
            };
        }"""
    )
    out: list[dict[str, Any]] = []
    # Core SEO
    if not data["title"]:
        out.append({"severity": "medium", "type": "seo", "detail": "Missing <title>"})
    elif len(data["title"]) > 60:
        out.append({"severity": "low", "type": "seo", "detail": f"<title> {len(data['title'])} chars (>60 truncates in SERP)"})
    if data["desc"] is None:
        out.append({"severity": "low", "type": "seo", "detail": "Missing meta description"})
    elif len(data["desc"]) > 160:
        out.append({"severity": "low", "type": "seo", "detail": f"Meta description {len(data['desc'])} chars (>160 truncates)"})
    if data["canonical"] is None:
        out.append({"severity": "low", "type": "seo", "detail": "No canonical link"})
    if data["h1"] == 0:
        out.append({"severity": "low", "type": "seo", "detail": "No <h1> on page"})
    elif data["h1"] > 1:
        out.append({"severity": "low", "type": "seo", "detail": f"{data['h1']} <h1> elements (should be 1)"})
    if data["viewport"] is None:
        out.append({"severity": "low", "type": "seo", "detail": "No viewport meta (not mobile-friendly)"})
    if (data["robots"] or "").lower().find("noindex") >= 0:
        out.append({"severity": "medium", "type": "seo", "detail": "Page is noindex — excluded from search"})
    # Open Graph
    if not data["ogTitle"]:
        out.append({"severity": "low", "type": "seo-og", "detail": "Missing og:title — poor social sharing preview"})
    if not data["ogDesc"]:
        out.append({"severity": "low", "type": "seo-og", "detail": "Missing og:description"})
    if not data["ogImage"]:
        out.append({"severity": "low", "type": "seo-og", "detail": "Missing og:image — no thumbnail on social share"})
    # Twitter Card
    if not data["twCard"]:
        out.append({"severity": "low", "type": "seo-twitter", "detail": "Missing twitter:card — no Twitter rich card"})
    # JSON-LD structured data
    if data["jsonLdCount"] == 0:
        out.append({"severity": "low", "type": "seo-jsonld", "detail": "No JSON-LD structured data — no rich results eligibility"})
    return out


async def _ux_render_checks(page) -> list[dict[str, Any]]:
    """Rendered-page UX checks that catch issues static HTML misses."""
    data = await page.evaluate(
        """() => {
            const viewportW = document.documentElement.clientWidth || window.innerWidth;
            const viewportH = document.documentElement.clientHeight || window.innerHeight;
            const bodyW = Math.max(
                document.body ? document.body.scrollWidth : 0,
                document.documentElement.scrollWidth || 0
            );
            const offscreen = [];
            const clippedText = [];
            const smallTargets = [];
            const fixedCovering = [];
            const visible = el => {
                const st = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return st.visibility !== 'hidden' && st.display !== 'none' &&
                    r.width > 0 && r.height > 0;
            };
            const label = el => {
                const id = el.id ? '#' + el.id : '';
                const cls = (el.className && typeof el.className === 'string')
                    ? '.' + el.className.trim().split(/\\s+/).slice(0,2).join('.') : '';
                return el.tagName.toLowerCase() + id + cls;
            };

            document.querySelectorAll('body *').forEach(el => {
                if (!visible(el)) return;
                const r = el.getBoundingClientRect();
                if ((r.right > viewportW + 2 || r.left < -2) && offscreen.length < 5) {
                    offscreen.push(label(el));
                }
                const st = getComputedStyle(el);
                const text = (el.textContent || '').trim();
                if (text && /(hidden|clip|scroll|auto)/.test(st.overflow + st.overflowX + st.overflowY)) {
                    if ((el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2) &&
                        clippedText.length < 5) clippedText.push(label(el));
                }
                if (el.matches('a[href],button,input,select,textarea,[role="button"],[tabindex]')) {
                    if ((r.width < 24 || r.height < 24) && smallTargets.length < 5) {
                        smallTargets.push(label(el) + ` (${Math.round(r.width)}x${Math.round(r.height)})`);
                    }
                }
                if ((st.position === 'fixed' || st.position === 'sticky') && r.width * r.height > viewportW * viewportH * 0.6) {
                    fixedCovering.push(label(el));
                }
            });
            return {
                horizontalOverflow: bodyW > viewportW + 2 ? Math.round(bodyW - viewportW) : 0,
                offscreen,
                clippedText,
                smallTargets,
                fixedCovering: fixedCovering.slice(0, 5),
            };
        }"""
    )
    findings: list[dict[str, Any]] = []
    if data.get("horizontalOverflow"):
        findings.append({
            "severity": "medium",
            "type": "visual-overflow",
            "detail": f"Page horizontally overflows viewport by {data['horizontalOverflow']} px",
            "evidence": "e.g. " + "; ".join(data.get("offscreen", [])[:3]) if data.get("offscreen") else "",
        })
    if data.get("clippedText"):
        findings.append({
            "severity": "medium",
            "type": "visual-clipped-text",
            "detail": f"{len(data['clippedText'])} visible text container(s) appear clipped",
            "evidence": "e.g. " + "; ".join(data["clippedText"][:3]),
        })
    if data.get("smallTargets"):
        findings.append({
            "severity": "low",
            "type": "ux-small-target",
            "detail": f"{len(data['smallTargets'])} interactive target(s) are smaller than 24px",
            "evidence": "e.g. " + "; ".join(data["smallTargets"][:3]),
        })
    if data.get("fixedCovering"):
        findings.append({
            "severity": "medium",
            "type": "ux-blocking-overlay",
            "detail": "Large fixed/sticky element covers most of the viewport",
            "evidence": "e.g. " + "; ".join(data["fixedCovering"][:3]),
        })
    return findings


async def run_qa(url: str) -> dict[str, Any]:
    """Load one page and collect findings across several quality dimensions."""
    page = await manager.page()
    manager.clear_logs()
    findings: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    resp = None
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = await page.goto(url, wait_until="load", timeout=30000)
            last_err = None
            break
        except Exception as e:
            last_err = e  # e.g. "interrupted by another navigation" — settle and retry
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
    if last_err is not None:
        return {
            "url": url,
            "ok": False,
            "findings": [{"severity": "high", "type": "load-failure", "detail": str(last_err)}],
        }
    load_ms = round((time.perf_counter() - t0) * 1000)

    status = resp.status if resp else None
    if status and status >= 400:
        findings.append(
            {"severity": "high", "type": "http-error", "detail": f"Page returned {status}"}
        )

    # Console errors / warnings.
    for c in manager.console:
        if c.type in ("error", "warning"):
            findings.append(
                {
                    "severity": "high" if c.type == "error" else "low",
                    "type": f"console-{c.type}",
                    "detail": c.text[:300],
                    "at": c.location,
                }
            )

    # Failed / erroring network requests.
    for n in manager.network:
        if n.failure:
            findings.append(
                {"severity": "high", "type": "request-failed", "detail": f"{n.method} {n.url} — {n.failure}"}
            )
        elif n.status and n.status >= 400:
            findings.append(
                {"severity": "medium", "type": "bad-response", "detail": f"{n.status} {n.method} {n.url}"}
            )

    # Deep accessibility audit (real WCAG checks incl. computed color contrast).
    try:
        a11y_result = await _a11y.audit(url, navigate=False)
        findings.extend(a11y_result.get("findings", []))
    except Exception as e:
        findings.append({"severity": "low", "type": "check-error", "detail": f"a11y: {e}"})

    # SEO signals.
    findings.extend(await _seo_checks(page))

    # Rendered UX / responsive signals.
    try:
        findings.extend(await _ux_render_checks(page))
    except Exception as e:
        findings.append({"severity": "low", "type": "check-error", "detail": f"ux-render: {e}"})

    # Performance signal.
    if load_ms > 4000:
        findings.append(
            {"severity": "medium", "type": "perf", "detail": f"Load took {load_ms} ms (>4s)"}
        )

    # Dedup identical findings (a retried load can double-fire console/network).
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for f in findings:
        key = (f.get("type", ""), f.get("detail", ""))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return {
        "url": url,
        "ok": True,
        "status": status,
        "load_ms": load_ms,
        "console_count": len(manager.console),
        "network_count": len(manager.network),
        "findings": unique,
    }


# --- security headers ------------------------------------------------------
_SEC_HEADERS = {
    "content-security-policy": ("high", "Missing CSP — XSS/injection risk"),
    "strict-transport-security": ("medium", "Missing HSTS — downgrade/MITM risk"),
    "x-frame-options": ("medium", "Missing X-Frame-Options — clickjacking risk"),
    "x-content-type-options": ("low", "Missing X-Content-Type-Options: nosniff"),
    "referrer-policy": ("low", "Missing Referrer-Policy"),
    "permissions-policy": ("low", "Missing Permissions-Policy"),
}


async def security_headers(url: str) -> dict[str, Any]:
    """Fetch a URL and check for missing/weak security response headers."""
    page = await manager.page()
    findings: list[dict[str, Any]] = []
    if not url.lower().startswith("http"):
        return {"url": url, "skipped": "security headers only apply to http(s)", "findings": []}
    resp = await page.request.get(url, timeout=20000)
    headers = {k.lower(): v for k, v in resp.headers.items()}

    for h, (sev, msg) in _SEC_HEADERS.items():
        if h not in headers:
            findings.append({"severity": sev, "type": "sec-header", "detail": msg})

    server = headers.get("server", "")
    if server and any(c.isdigit() for c in server):
        findings.append(
            {"severity": "low", "type": "info-leak", "detail": f"Server header leaks version: {server}"}
        )
    if "x-powered-by" in headers:
        findings.append(
            {"severity": "low", "type": "info-leak", "detail": f"X-Powered-By leaks stack: {headers['x-powered-by']}"}
        )
    return {"url": url, "status": resp.status, "headers_present": sorted(headers), "findings": findings}


# --- broken link checker ---------------------------------------------------
async def check_links(url: str, max_links: int = 100) -> dict[str, Any]:
    """Collect links on a page and probe each; report broken ones (4xx/5xx/fail)."""
    page = await manager.page()
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    hrefs = await page.eval_on_selector_all(
        "a[href]", "els => [...new Set(els.map(e => e.href))]"
    )
    hrefs = [h for h in hrefs if h.startswith("http")][:max_links]
    findings: list[dict[str, Any]] = []
    checked = 0
    for h in hrefs:
        try:
            r = await page.request.head(h, timeout=15000)
            st = r.status
            # Many servers reject HEAD (405/501) or bot HEADs (403/401) yet serve
            # the resource fine on GET — retry before calling it broken.
            if st in (401, 403, 405, 501):
                r = await page.request.get(h, timeout=15000)
                st = r.status
            checked += 1
            # 401/403 = reachable but access-controlled, not a dead link.
            if st in (401, 403):
                continue
            if st >= 400:
                findings.append(
                    {"severity": "medium", "type": "broken-link", "detail": f"{st} → {h}"}
                )
        except Exception as e:
            findings.append({"severity": "medium", "type": "broken-link", "detail": f"unreachable → {h} ({e})"})
    return {"url": url, "links_checked": checked, "findings": findings}


# --- form auditor ----------------------------------------------------------
async def test_forms(url: str) -> dict[str, Any]:
    """Static + DOM audit of every form on a page. Non-destructive (no submit)."""
    page = await manager.page()
    await page.goto(url, wait_until="load", timeout=20000)
    forms = await page.evaluate(
        """() => [...document.forms].map(f => ({
            action: f.getAttribute('action') || location.href,
            method: (f.getAttribute('method') || 'get').toLowerCase(),
            fields: [...f.elements].filter(e => e.name || e.id).map(e => ({
                name: e.name || e.id, type: e.type,
                required: e.required, hasLabel: !!(e.labels && e.labels.length) ||
                    !!e.getAttribute('aria-label'),
                autocomplete: e.getAttribute('autocomplete') || ''
            }))
        }))"""
    )
    findings: list[dict[str, Any]] = []
    for i, f in enumerate(forms):
        tag = f"form#{i} ({f['method'].upper()} {f['action']})"
        if f["method"] == "get" and any(
            fld["type"] == "password" for fld in f["fields"]
        ):
            findings.append({"severity": "high", "type": "form-security", "detail": f"{tag} submits a password over GET"})
        if str(f["action"]).startswith("http://"):
            findings.append({"severity": "high", "type": "form-security", "detail": f"{tag} posts to insecure http://"})
        for fld in f["fields"]:
            if not fld["hasLabel"] and fld["type"] not in ("hidden", "submit", "button"):
                findings.append({"severity": "low", "type": "form-a11y", "detail": f"{tag} field {fld['name']!r} has no label"})
            if fld["type"] == "password" and fld["autocomplete"] not in ("new-password", "current-password"):
                findings.append({"severity": "low", "type": "form-hint", "detail": f"{tag} password field missing autocomplete hint"})
            if not fld["required"] and fld["type"] in ("email", "password", "tel"):
                findings.append({"severity": "low", "type": "form-validation", "detail": f"{tag} {fld['type']} field {fld['name']!r} not marked required"})
    return {"url": url, "forms": len(forms), "findings": findings}


async def _mobile_ux_check(url: str) -> list[dict[str, Any]]:
    """Re-run visual/UX checks at a 375×812 mobile viewport. Catches responsive
    breakage that only appears on small screens. Restores desktop viewport after."""
    page = await manager.page()
    findings: list[dict[str, Any]] = []
    try:
        await page.set_viewport_size({"width": 375, "height": 812})
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        mobile_findings = await _ux_render_checks(page)
        for f in mobile_findings:
            f["viewport"] = "mobile-375"
            f["type"] = "mobile-" + f.get("type", "ux")
        findings.extend(mobile_findings)
        # Check for fixed/sticky elements that cover >50% of mobile viewport
        overlay = await page.evaluate(
            """() => {
                const vw = window.innerWidth, vh = window.innerHeight;
                const blocking = [];
                document.querySelectorAll('*').forEach(el => {
                    const s = getComputedStyle(el);
                    if ((s.position === 'fixed' || s.position === 'sticky')) {
                        const r = el.getBoundingClientRect();
                        if (r.width * r.height > vw * vh * 0.4) {
                            const id = el.id ? '#'+el.id : '';
                            blocking.push(el.tagName.toLowerCase() + id);
                        }
                    }
                });
                return blocking.slice(0, 5);
            }"""
        )
        if overlay:
            findings.append({
                "severity": "medium", "type": "mobile-overlay",
                "detail": f"Fixed/sticky element covers >40% of 375px mobile viewport",
                "evidence": "e.g. " + "; ".join(overlay[:3]),
                "viewport": "mobile-375",
            })
    except Exception as e:
        findings.append({"severity": "low", "type": "check-error",
                         "detail": f"mobile-ux: {e}", "viewport": "mobile-375"})
    finally:
        # Restore desktop viewport
        try:
            await page.set_viewport_size({"width": 1280, "height": 800})
        except Exception:
            pass
    return findings


async def deep_test(
    url: str,
    max_pages: int = 50,
    security: bool = True,
    perf: bool = True,
    keyboard: bool = True,
    fuzz: bool = True,
) -> dict[str, Any]:
    """Comprehensive test: crawl ALL discoverable pages (sitemap + SPA routes +
    nav links + BFS), then per page run:
      - QA: console errors, network failures, a11y (WCAG 2.1), SEO (incl. OG/Twitter/JSON-LD)
      - Forms: static audit + active fuzz (injection/unicode/boundary/invalid data)
      - Security: headers + advanced probes (CSP, SSTI, LFI, CRLF, host-header, GraphQL)
      - Performance: real Core Web Vitals (LCP/CLS/TBT/FCP/TTFB)
      - Keyboard: reachability and focus-trap detection
      - Mobile: responsive layout check at 375px viewport
    Every finding is evidence-backed — no fabricated results.
    Pass max_pages=200 or higher for very large sites.
    Set fuzz=False to skip active form fuzzing (faster, less intrusive)."""
    from . import uat as _uat

    crawl_result = await crawl(url, max_pages)
    results: list[dict[str, Any]] = []

    for p in crawl_result["pages"]:
        if p.get("error") or (p.get("status") and p["status"] >= 400):
            continue
        page_url = p["url"]
        merged = await run_qa(page_url)

        # Core checks: static form audit + security headers
        checks = [test_forms, security_headers]
        if security:
            checks.append(_advsec.advanced_scan)
        if keyboard:
            checks.append(_uat.keyboard_walk)
        for check in checks:
            try:
                merged["findings"].extend((await check(page_url)).get("findings", []))
            except Exception as e:
                merged["findings"].append(
                    {"severity": "low", "type": "check-error", "detail": f"{check.__name__} failed: {e}"}
                )

        # Active form fuzzing: injection / unicode / boundary / invalid data per field
        if fuzz:
            try:
                fuzz_result = await _fuzz_forms(page_url)
                merged["findings"].extend(fuzz_result.get("findings", []))
                merged["fuzz_cases_tested"] = fuzz_result.get("cases_tested", 0)
                merged["fuzz_scenario_matrix"] = fuzz_result.get("scenario_matrix", [])
            except Exception as e:
                merged["findings"].append(
                    {"severity": "low", "type": "check-error", "detail": f"fuzz_forms failed: {e}"}
                )

        # Performance vitals
        if perf:
            try:
                v = await _vitals.measure(page_url)
                merged["perf_score"] = v["score"]
                merged["vitals"] = v["metrics"]
                merged["findings"].extend(v.get("findings", []))
            except Exception as e:
                merged["findings"].append({"severity": "low", "type": "check-error", "detail": f"vitals: {e}"})

        # Mobile viewport responsive check (375px)
        try:
            mobile_findings = await _mobile_ux_check(page_url)
            merged["findings"].extend(mobile_findings)
        except Exception as e:
            merged["findings"].append(
                {"severity": "low", "type": "check-error", "detail": f"mobile-ux failed: {e}"}
            )

        # Dedup after merging many sources.
        seen: set[tuple[str, str]] = set()
        uniq = []
        for f in merged["findings"]:
            k = (f.get("type", ""), f.get("detail", ""))
            if k not in seen:
                seen.add(k)
                uniq.append(f)
        merged["findings"] = uniq
        results.append(merged)

    tested_set = {r.get("url") for r in results}
    skipped_urls = [
        p.get("url") for p in crawl_result.get("pages", [])
        if p.get("url") not in tested_set
    ]
    coverage = {
        "start": url,
        "crawl_pages": crawl_result.get("crawled", 0),
        "seed_sources": crawl_result.get("seed_sources", []),
        "pages_tested": len(results),
        "max_pages": max_pages,
        "tested_urls": [r.get("url") for r in results],
        "skipped_urls": skipped_urls,
        "complete": bool(results) and len(results) >= min(crawl_result.get("crawled", 0), max_pages),
    }
    if len(results) <= 1:
        coverage["status"] = "limited"
        coverage["reason"] = (
            "Only one reachable page was tested. If the product has an authenticated "
            "dashboard or private workflows, log in or load a saved session before "
            "rerunning deep_test. For SPA apps with JS-only routes, increase max_pages "
            "and ensure the app is fully loaded before crawl."
        )
        coverage["not_tested"] = [
            "authenticated dashboard and all private routes",
            "account/workspace authorization and IDOR surface",
            "campaign or primary business creation flow",
            "settings, integrations, billing, and role permissions",
            "saved-data persistence, reload/back behavior, and recovery paths",
            "dynamic routes only reachable after user interaction",
        ]
    elif skipped_urls:
        coverage["status"] = "partial"
        coverage["reason"] = (
            f"max_pages={max_pages} reached before all discovered pages were tested. "
            f"{len(skipped_urls)} pages were discovered but not tested. "
            "Increase max_pages or run deep_test on skipped_urls individually."
        )
        coverage["not_tested"] = skipped_urls[:50]
    else:
        coverage["status"] = "complete"
        coverage["reason"] = (
            "All discovered in-scope pages (via sitemap, SPA routes, nav links, and BFS) "
            "were tested within max_pages."
        )
        coverage["not_tested"] = []

    if results:
        results[0]["coverage"] = coverage
    return {"start": url, "pages_tested": len(results), "coverage": coverage, "results": results}
