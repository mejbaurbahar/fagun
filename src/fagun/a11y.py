"""Deep accessibility audit — real WCAG 2.1 checks run in the live DOM.

Every finding is computed from actual rendered elements and (for contrast) the
real computed colors, so results are verifiable — this returns *counts with
example selectors*, never a fabricated pass/fail. No external library is loaded;
the checks are implemented directly against the DOM/CSSOM.
"""

from __future__ import annotations

from typing import Any

from .browser import manager

# One big JS pass so we touch the DOM once. Returns structured issue buckets,
# each with a count and up to 5 example selectors as evidence.
_AUDIT_JS = r"""
() => {
  const ex = (els, n=5) => [...els].slice(0, n).map(e => {
    const id = e.id ? '#' + e.id : '';
    const cls = (e.className && typeof e.className === 'string')
      ? '.' + e.className.trim().split(/\s+/).slice(0,2).join('.') : '';
    return e.tagName.toLowerCase() + id + cls;
  });
  const R = {};

  // 1. Images without alt (decorative alt="" is fine)
  const imgsNoAlt = [...document.querySelectorAll('img:not([alt]):not([role="presentation"])')];
  R.imgAlt = {count: imgsNoAlt.length, ex: ex(imgsNoAlt)};

  // 2. Form controls without accessible name
  const badInputs = [...document.querySelectorAll('input,select,textarea')].filter(el => {
    if (['hidden','submit','button','reset','image'].includes(el.type)) return false;
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.title) return false;
    if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return false;
    return !el.closest('label');
  });
  R.inputLabel = {count: badInputs.length, ex: ex(badInputs)};

  // 3. Buttons / links with no discernible text
  const emptyBtns = [...document.querySelectorAll('button,a[href],[role="button"]')].filter(el => {
    const t = (el.textContent || '').trim();
    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.title;
    const img = el.querySelector('img[alt]:not([alt=""])');
    return !t && !aria && !img;
  });
  R.emptyControl = {count: emptyBtns.length, ex: ex(emptyBtns)};

  // 4. Heading order (skipped levels) & missing h1
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')];
  let skips = 0, last = 0;
  for (const h of heads) { const lvl = +h.tagName[1]; if (last && lvl - last > 1) skips++; last = lvl; }
  R.headingOrder = {count: skips, ex: []};
  R.noH1 = {count: document.querySelector('h1') ? 0 : 1, ex: []};

  // 5. html[lang]
  R.htmlLang = {count: document.documentElement.getAttribute('lang') ? 0 : 1, ex: []};

  // 6. Document title
  R.docTitle = {count: (document.title || '').trim() ? 0 : 1, ex: []};

  // 7. Duplicate ids (break aria/label references)
  const ids = {}; let dup = 0;
  document.querySelectorAll('[id]').forEach(e => { ids[e.id] = (ids[e.id]||0)+1; });
  const dupIds = Object.keys(ids).filter(k => ids[k] > 1);
  R.dupId = {count: dupIds.length, ex: dupIds.slice(0,5)};

  // 8. Positive tabindex (breaks natural focus order)
  const posTab = [...document.querySelectorAll('[tabindex]')].filter(e => +e.getAttribute('tabindex') > 0);
  R.positiveTabindex = {count: posTab.length, ex: ex(posTab)};

  // 9. Links opening new tab without rel=noopener (security + a11y)
  const unsafeBlank = [...document.querySelectorAll('a[target="_blank"]')].filter(a => {
    const rel = (a.getAttribute('rel')||'').toLowerCase();
    return !rel.includes('noopener');
  });
  R.targetBlank = {count: unsafeBlank.length, ex: ex(unsafeBlank)};

  // 10. Invalid ARIA roles
  const VALID = new Set(['alert','alertdialog','application','article','banner','button','cell','checkbox','columnheader','combobox','complementary','contentinfo','definition','dialog','directory','document','feed','figure','form','grid','gridcell','group','heading','img','link','list','listbox','listitem','log','main','marquee','math','menu','menubar','menuitem','menuitemcheckbox','menuitemradio','navigation','none','note','option','presentation','progressbar','radio','radiogroup','region','row','rowgroup','rowheader','scrollbar','search','searchbox','separator','slider','spinbutton','status','switch','tab','table','tablist','tabpanel','term','textbox','timer','toolbar','tooltip','tree','treegrid','treeitem']);
  const badRole = [...document.querySelectorAll('[role]')].filter(e => {
    return e.getAttribute('role').split(/\s+/).some(r => r && !VALID.has(r));
  });
  R.badRole = {count: badRole.length, ex: ex(badRole)};

  // 11. Color contrast (WCAG AA: 4.5:1 normal, 3:1 large). Real computed colors.
  const lum = (r,g,b) => {
    const a = [r,g,b].map(v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); });
    return 0.2126*a[0] + 0.7152*a[1] + 0.0722*a[2];
  };
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(s => parseFloat(s)); if (p.length>=4 && p[3]===0) return null; return p; };
  const bgOf = (el) => { let n = el; while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c) return c; n = n.parentElement; } return [255,255,255]; };
  const textEls = [...document.querySelectorAll('p,span,a,li,td,th,label,h1,h2,h3,h4,h5,h6,button,div')]
    .filter(e => e.childNodes.length && [...e.childNodes].some(n => n.nodeType===3 && n.textContent.trim()));
  let low = 0; const lowEx = [];
  for (const el of textEls.slice(0, 400)) {
    const st = getComputedStyle(el);
    const fg = parse(st.color); if (!fg) continue;
    const bg = bgOf(el);
    const L1 = lum(fg[0],fg[1],fg[2]) + 0.05, L2 = lum(bg[0],bg[1],bg[2]) + 0.05;
    const ratio = L1 > L2 ? L1/L2 : L2/L1;
    const size = parseFloat(st.fontSize), bold = +st.fontWeight >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5;
    if (ratio < need) { low++; if (lowEx.length < 5) lowEx.push(ex([el])[0] + ` (${ratio.toFixed(2)}:1, need ${need})`); }
  }
  R.contrast = {count: low, ex: lowEx, sampled: Math.min(textEls.length, 400)};

  // 12. Viewport meta blocking zoom (user-scalable=no / maximum-scale=1)
  const vp = document.querySelector('meta[name="viewport"]');
  const vc = vp ? (vp.getAttribute('content')||'').toLowerCase() : '';
  R.noZoom = {count: (/user-scalable\s*=\s*no|maximum-scale\s*=\s*1(\.0)?\b/.test(vc)) ? 1 : 0, ex: []};

  // 13. iframes without a title attribute (screen readers can't identify them)
  const badIframes = [...document.querySelectorAll('iframe')].filter(el => {
    const t = (el.getAttribute('title') || '').trim();
    return !t;
  });
  R.iframeTitle = {count: badIframes.length, ex: ex(badIframes)};

  // 14. Interactive elements with no visible focus indicator (focus-visible check)
  // We check if any interactive element has outline:none + no box-shadow fallback
  const noFocus = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]')]
    .filter(el => {
      const st = getComputedStyle(el);
      const outline = st.outlineWidth && parseFloat(st.outlineWidth) > 0;
      const boxShadow = st.boxShadow && st.boxShadow !== 'none';
      return !outline && !boxShadow;
    });
  R.noFocusIndicator = {count: noFocus.length, ex: ex(noFocus)};

  return R;
}
"""

# (bucket, severity, message template) — count>0 => finding.
_RULES = [
    ("imgAlt", "medium", "images missing alt text"),
    ("inputLabel", "high", "form controls with no accessible label"),
    ("emptyControl", "high", "buttons/links with no discernible text"),
    ("contrast", "medium", "text elements below WCAG AA contrast"),
    ("headingOrder", "low", "skipped heading levels"),
    ("noH1", "low", "page has no <h1>"),
    ("htmlLang", "medium", "<html> missing lang attribute"),
    ("docTitle", "medium", "document has no <title>"),
    ("dupId", "medium", "duplicate id attributes (break aria/label refs)"),
    ("positiveTabindex", "low", "positive tabindex disrupts focus order"),
    ("targetBlank", "medium", "target=_blank links without rel=noopener"),
    ("badRole", "medium", "invalid ARIA role values"),
    ("noZoom", "medium", "viewport blocks pinch-zoom (user-scalable=no)"),
    ("iframeTitle", "medium", "iframes without title attribute (screen readers can't identify)"),
    ("noFocusIndicator", "low", "interactive elements with no visible focus indicator"),
]


async def audit(url: str, navigate: bool = True) -> dict[str, Any]:
    """Run the full a11y audit against a page. Returns findings with evidence."""
    page = await manager.page()
    if navigate:
        await page.goto(url, wait_until="load", timeout=30000)
    data = await page.evaluate(_AUDIT_JS)
    findings: list[dict[str, Any]] = []
    for key, sev, msg in _RULES:
        bucket = data.get(key, {})
        n = bucket.get("count", 0)
        if not n:
            continue
        ex = bucket.get("ex", [])
        detail = f"{n} {msg}" if n > 1 or key in ("imgAlt", "inputLabel", "contrast") else msg
        f = {"severity": sev, "type": f"a11y-{key}", "detail": detail}
        if ex:
            f["evidence"] = "e.g. " + "; ".join(str(e) for e in ex[:3])
        findings.append(f)
    return {"url": url, "findings": findings, "raw": data}
