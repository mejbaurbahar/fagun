# Landing-page design prompt for Fagun

Paste the block below into Claude (or any design tool). It describes a hero landing
page in the same spirit as the browser-harness site (pixel-art hero, serif italic
headline, warm gold accent on a dark scene) but themed for **Fagun** 🦊.

---

Build a single, self-contained landing page (one HTML file, all CSS inline, no
external assets — embed any image as a data URI or use a pure-CSS/SVG background).
It must be fully responsive and never scroll horizontally.

**Product:** Fagun — an open-source tool that gives any AI (Claude, Cursor, Codex,
Antigravity, Windsurf) a real browser to drive, so it can run full QA and hunt real
bugs on any website. One MCP server, works in every AI tool, Chrome installs itself,
token-lean by default, self-healing (the agent writes its own missing helpers).

**Overall vibe:** cinematic, premium, a little mythic — like the browser-harness
"self-healing browser agents" page. A large atmospheric hero image behind the fold,
dark moody background, a single warm accent color, big editorial serif headline with
one word in italic gold. Confident and minimal, not corporate. A fox (🦊) is the mascot
— work it in tastefully (small logo mark, subtle motif), don't make it cartoonish.

**Color & type:**
- Background: deep twilight — near-black indigo/plum gradient (#0d0b16 → #241a33).
- Accent: warm amber-gold (#E8B04B) used sparingly (one headline word, buttons, links).
- Text: warm off-white (#F3EEE6) for body, muted lavender-grey for secondary.
- Headline font: a high-contrast serif (e.g. Playfair Display / Cormorant vibe) —
  huge, tight leading, with ONE word set in italic gold.
- Body/labels: a clean grotesque sans (Inter/Söhne vibe). Small-caps tracked-out
  eyebrow label.

**Hero section (above the fold):**
- Top bar: fox logo mark + "Fagun" wordmark on the left; a "GitHub" pill button
  (top-right) linking to https://github.com/mejbaurbahar/fagun.
- Eyebrow (small-caps, gold, letter-spaced): `BROWSER + QA AGENT · OPEN SOURCE`.
- Headline (two lines, massive):
  line 1 — *Bug-hunting* (italic, gold)
  line 2 — browser agents. (upright, off-white)
- Subhead (2 short paragraphs, muted):
  "Fagun gives any AI a real browser — to click, crawl, and find real bugs:
  broken links, console errors, failed requests, form flaws, a11y gaps, security
  misconfigs."
  "Works in Claude, Cursor, Codex & more. Chrome installs itself. Token-lean by default."
- Two CTAs side by side:
  primary (solid gold, dark text): `⧉ Prompt for LLMs` (copies the setup prompt to
  clipboard — see below).
  secondary (outline): `★ Star on GitHub` → the repo.
- Background: a wide, atmospheric pixel-art / painterly scene (twilight sky, distant
  ruins or a lone path) rendered in pure CSS gradients + a few absolutely-positioned
  SVG shapes if you can't embed an image. Keep it subtle behind a dark overlay so
  text stays readable.

**"Copy this prompt" behavior:** the primary button copies this exact text to the
clipboard and shows a "Copied!" toast:
> Install and set up fagun for me: install `uv` if missing, run `uvx fagun setup`,
> then `uvx fagun install claude-code`. Follow
> https://github.com/mejbaurbahar/fagun/blob/main/install.md if anything fails.

**Below the fold (keep it tight — 3 short bands):**
1. **Install in one line** — a dark code card showing:
   `uvx fagun install claude-code` and, under it, the plugin option
   `/plugin marketplace add mejbaurbahar/fagun` → `/plugin install fagun@fagun`.
   One sentence: "No Python, no pip — uv brings its own. Chrome auto-installs."
2. **What it finds** — a responsive grid of 6–10 small cards, each an icon + label:
   Broken links · Console/JS errors · Failed requests · Form & validation flaws ·
   Accessibility · Performance · Exposed files & secrets · CORS / headers ·
   Reflected XSS & open redirect · Self-healing (writes its own helpers).
3. **Works everywhere** — a quiet row of tool names: Claude Code · Claude Desktop ·
   Cursor · Codex · Antigravity · Windsurf · Cline · VS Code.

**Footer:** small — "MIT © Mejbaur Bahar Fagun" + GitHub link + the fox mark.

**Constraints:** one file, self-contained, no external fonts/CDN/images (inline or
system-font fallback stack that mimics the serif/sans intent), accessible contrast,
mobile-first responsive, wide code blocks scroll inside their own container. Add a
tasteful subtle entrance animation on the headline only. Favicon: 🦊.
