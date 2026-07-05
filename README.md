# 🦊 Fagun

**Give any AI a browser to use your product like real customers, run full UAT, hunt real bugs, and tell you if it's ready to ship.**

Fagun is a single tool that plugs into **Claude, Cursor, Codex, Antigravity, Windsurf,
Cline, or VS Code**. Once it's set up, you just type **`fagun`** (or `/fagun`) and your
AI can open a real browser and:

- **Use the site as real end users** — mobile, slow-internet, low-end, keyboard-only,
  screen-reader, international, first-time visitor — with real device + network emulation.
- **Run User Acceptance Testing** — walk complete journeys (signup, login, search,
  checkout, password reset…) step by step and confirm a real user can finish them.
- **Hunt real, reproducible bugs** — broken links, console/JS errors, failed requests,
  form-validation gaps, accessibility violations, slow pages, security misconfig.
- **Deliver a product-readiness verdict** — a 16-category scorecard (UX, UI, business
  logic, a11y, perf, security…) and a release decision, with prioritized fixes.

You set it up **once**. It works in **every** AI tool. Chrome installs **itself**.

🌐 **Website:** https://mejbaurbahar.github.io/fagun/ · 📦 **PyPI:** https://pypi.org/project/fagun/

---

## ⚡ One command sets up everything

```bash
uvx fagun init
```

That's the whole install. `fagun init` installs the Chrome engine **and** auto-detects
every AI tool on your machine (Claude Code, Claude Desktop, Cursor, Codex, Windsurf)
and registers the fagun browser tools, **Chrome DevTools MCP**, **+** the `/fagun`
skill in each one. It also opens `chrome://inspect/#remote-debugging` so Chrome
can show the official **Allow remote debugging?** popup when Fagun attaches to
your signed-in default Chrome session.

Then restart your AI tool and type **`fagun`** — followed by what you want tested.

> Prefer pip? `pip install fagun && fagun init` does the same thing.

<details>
<summary>Other ways to install</summary>

**Paste-prompt** (let the AI do it):
> Install and set up **fagun** for me: install `uv` if missing, then run `uvx fagun init`.
> Follow https://github.com/mejbaurbahar/fagun/blob/main/install.md if anything fails.

**Claude Code plugin:**
```
/plugin marketplace add mejbaurbahar/fagun
/plugin install fagun@fagun
```

**Target one tool:**
```bash
uvx fagun install claude-code   # or: cursor | claude | vscode
```
</details>

<details>
<summary>Don't have <code>uv</code> yet? (one line, no Python needed)</summary>

**macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
**Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
Then restart your terminal.
</details>

---

## 🚀 Manual install (any OS — no Python or pip needed)

**Step 1 — install `uv`** (it brings its own Python, so nothing else is required):

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
> ⚠️ **Restart your terminal** after this so `uv` is on your PATH.
> (macOS/Linux: or run `source $HOME/.local/bin/env` in the current shell.)

**Step 2 — set up Fagun:**
```bash
uvx fagun setup      # installs the Chrome engine automatically
uvx fagun install    # shows the config to paste into your AI tool
```

That's it. Restart your AI tool, type **`fagun`**, and go.

> **Already have `pip`/Python?** `pip install uv` also works — but the installer
> above needs no Python at all, which is why we recommend it.

> 💡 Don't want to think about config? Just tell your AI:
> *"Install and set up fagun for me — follow https://github.com/mejbaurbahar/fagun/blob/main/install.md"*
> and it does everything above for you.

---

## 🔌 Connect it to your AI tool

Every tool gets two MCP servers:

- **fagun** — UAT, bug hunting, security, a11y, forms, reports.
- **chrome-devtools** — official Chrome DevTools MCP for live DevTools debugging,
  console/network inspection, DOM/CSS inspection, and performance traces.

`uvx fagun init` writes both automatically. Manual config:

| Tool | How |
|------|-----|
| **Claude Code** | `claude mcp add fagun -- uvx fagun` and `claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --auto-connect --no-usage-statistics` |
| **Claude Desktop** | add the JSON below to `claude_desktop_config.json` |
| **Cursor** | `uvx fagun install cursor` (writes `~/.cursor/mcp.json`) |
| **VS Code (Copilot)** | `uvx fagun install vscode` (writes `.vscode/mcp.json`) |
| **Windsurf / Cline / Antigravity** | paste the JSON below into their MCP settings |
| **Codex CLI** | add the TOML below to `~/.codex/config.toml` |

```jsonc
// Claude Desktop / Cursor / Windsurf / Cline / Antigravity
{
  "mcpServers": {
    "fagun": { "command": "uvx", "args": ["fagun"] },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"],
      "env": {
        "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
        "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1"
      }
    }
  }
}
```

```toml
# Codex — ~/.codex/config.toml
[mcp_servers.fagun]
command = "uvx"
args = ["fagun"]

[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]
env = { CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1", CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = "1" }
startup_timeout_ms = 20_000
```

The `-y` flag prevents `npx` from asking the user to confirm package download.
`--auto-connect` makes Chrome DevTools MCP attach to the user's running Chrome.
On first setup, Fagun opens `chrome://inspect/#remote-debugging`; turn on remote
debugging there, then click **Allow** when Chrome shows the permission popup.
Users do not need to run `fagun connect to my Chrome` first; `fagun deep test <url>`
should auto-use Chrome DevTools MCP when the AI client exposes it.
Fagun opts out of Chrome DevTools MCP usage statistics and update-check noise in
generated configs.

**Restart the tool after adding it.** Then type `fagun`.

---

## 🎬 See it in action

▶️ **Live animated demo (macOS / Windows / Linux):** https://mejbaurbahar.github.io/fagun/#see-it-in-action

Setup + first bug on each OS:

**macOS / Linux**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # get uv (once)
uvx fagun init                                     # browser + all AI tools + skill
# then, inside your AI tool, type:
#   fagun deep test https://example.com
```

**Windows (PowerShell)**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # get uv (once)
uvx fagun init                                     # browser + all AI tools + skill
# then, inside your AI tool, type:
#   fagun audit https://example.com
```

That's the whole flow: **install uv → `uvx fagun init` → type `fagun <task>`** in any AI tool.

## 💬 How to use it

Just talk to your AI in plain English:

- `fagun` → shows the menu and starts up
- `go to example.com and take a screenshot`
- `run QA on https://example.com`
- `deep test https://example.com and save the report to ./report.md`
- `check for broken links on https://example.com`
- `test the forms on the signup page`
- `are there any console errors?` · `any failed network requests?`
- `log in with test@x.com / password123, then check the dashboard`

### 🕵️ The `/fagun` bug hunter

Fagun ships with a skill that turns your AI into a methodical QA tester. It sweeps
**10 kinds of problems** and only reports bugs it can actually reproduce (no guessing):

| # | Checks for |
|---|-----------|
| 1 | **Functional** — broken journeys, buttons/links that lie |
| 2 | **JavaScript errors** — crashes, console errors on load & on click |
| 3 | **Network / API** — 4xx/5xx, failed calls, mixed content |
| 4 | **Forms** — missing validation, insecure submission, no labels |
| 5 | **Auth / sessions** — login errors, leaks, access control |
| 6 | **Accessibility** — missing alt text, labels, keyboard traps |
| 7 | **Performance** — slow loads, heavy resources |
| 8 | **Visual / responsive** — layout breakage, overflow, cut-off text |
| 9 | **Security** — missing CSP/HSTS, exposed versions, secrets in code |
| 10 | **Edge cases** — reloads, back button, huge inputs, offline |

Every finding comes with **steps to reproduce, what was observed, and the impact.**

---

## 🪙 Token-saving (on by default)

Browser tools normally flood your AI's context with huge JSON blobs and full
network/console dumps — burning tokens fast. Fagun is built to be **token-lean**:

- **Terse output by default** — compact one-line-per-finding text instead of pretty
  JSON (~70% fewer tokens per result). Set `FAGUN_TERSE=0` for full JSON, or pass
  `verbose=true` to any tool for one call.
- **One call, not ten** — `deep_test` crawls + checks console, network, forms,
  headers, a11y, perf across the whole site in a **single** tool call, instead of
  many manual `navigate` + `get_console` + `get_network` round-trips.
- **Capped & deduped** — long link/console/network lists are truncated with a
  `+N more` marker; duplicate findings are collapsed.
- **Reports go to disk, not context** — pass `report_path` and raw detail is
  written there; the final chat answer still shows the full user-facing result:
  verdict, all findings, evidence, fixes, coverage, and report link.

> 💡 Cheapest workflow: `deep test <url> and save the report to ./report.md`
> → one call, full Fagun answer in chat, raw evidence/report on disk.

## ⚙️ Options (optional)

Set these as environment variables if you need them:

| Variable | Default | What it does |
|----------|---------|--------------|
| `FAGUN_HEADLESS` | `1` | Set to `0` to **watch** the browser work |
| `FAGUN_BROWSER` | `chromium` | Use `firefox` or `webkit` instead |
| `FAGUN_CDP_URL` | — | Attach to **your own** open Chrome, e.g. `http://127.0.0.1:9222` |
| `FAGUN_TERSE` | `1` | Compact token-lean output. Set `0` for full JSON or `mini` for extra-short summaries. |
| `FAGUN_FINDING_CAP` | `40` | Max findings shown per page in chat output. Full report still goes to disk. |
| `FAGUN_PAGE_CAP` | `12` | Max pages shown in multi-page chat summaries. |
| `FAGUN_DETAIL_CHARS` | `100` | Max chars per finding detail in terse output. |
| `FAGUN_URL_CHARS` | `60` | Max chars per URL in terse output. |

For the lowest-token workflow, use:

```bash
FAGUN_TERSE=mini
```

Then ask: `deep test <url> and save the report to ./fagun-report.html`. The chat
gets a tiny summary; the full evidence stays in the report file.

## 🎨 Fagun Style (same output across models)

Fagun ships a reusable response contract so Claude, Codex, Cursor, Gemini, Qwen,
DeepSeek, or a custom wrapper can show results in the same style:

- `fagun_style_prompt` — copy into system/custom instructions for Markdown output.
- `fagun_style_prompt(mode="json")` — tells the model to return structured JSON.
- `fagun_style_schema` — JSON schema for a frontend renderer with cards/panels.
- `fagun_render_response` — converts JSON or plain text into Fagun-style Markdown.

Default sections: Executive Summary, Problem, Analysis, Solution, Implementation,
Test Cases, Edge Cases, Risks, Production Impact, API Validation, Performance,
Jira Ticket, and Final Recommendation.

## 🧠 Advanced security prompt + tool catalog

For deeper authorized bug-hunting workflows, Fagun now includes an AI security
engineer prompt and an external-tool catalog. It does **not** blindly run exploit
tools; it plans adapters, explains when each tool fits, and keeps execution
scope-gated:

- `fagun_security_prompt` — improved enterprise prompt for authorized security testing.
- `list_external_security_tools` — catalog for Loxs, Skill Security Scanner,
  Shannon, Lonkero, recon-skills, payload corpora, RFC822 Email Validator,
  LostFuzzer, img-payloads, customBsqli, BeeXSS, TimeVault, and NextSploit.
- `recommend_security_tools` — picks the smallest relevant tool plan from the
  target profile and goal, then tells the AI how to validate and report evidence.

Use it for attack-graph planning, tool selection, deduplication, validation,
remediation, and regression tests. Active probes still require authorization.

`recon-skills` is treated as a read-only methodology pack first: Fagun can use it
to pick relevant recon, red-team, sector, chain, SAML, Docker, WordPress, CORS,
XMLRPC, JS-secret, metrics, and API-flow checklists, then translate those into
authorized Fagun-safe test plans.

---

## 🔐 Security scanning (authorized targets only)

`security scan <url>` runs the bug classes hunters get paid for — **non-destructive**,
GET/HEAD only, no attacks on third parties:

- Exposed files (`/.git`, `/.env`, `/.aws/credentials`, backups, actuator)
- Leaked secrets in HTML/JS (AWS, Stripe, Google, GitHub, JWT, private keys)
- CORS misconfiguration · reflected-XSS candidates · open redirect · SQLi error signals
- Cookie flags · security headers (CSP/HSTS/X-Frame)

> ⚠️ Only scan sites you own or are authorized to test.

## 🔌 Use your own logged-in Chrome (self-healing + sessions)

- Chrome DevTools MCP uses `--auto-connect` during normal deep tests, so it can
  reuse your already-signed-in default Chrome after you allow remote debugging.
  Great for testing behind a login without giving credentials to the AI.
- `connect to my Chrome` is only a troubleshooting fallback that launches a
  dedicated debuggable Chrome profile and attaches to it.
- `browser_exec` → when no built-in tool fits, the AI writes Python against the live
  page (full Playwright). `save_helper` persists what works, so Fagun gets smarter
  every run.

## 🧰 Everything it can do (MCP tools)

`fagun_start` · `open_browser` · `navigate` · `click` · `fill` · `press_key` ·
`screenshot` · `evaluate_js` · `get_console` · `get_network` · `crawl` · `run_qa` ·
`check_links` · `test_forms` · `fuzz_forms` · `list_test_data` · `perf_audit` ·
`a11y_audit` · `security_headers` · `security_scan` · `advanced_security` ·
`deep_test` · `full_qa_sweep` · `write_report` · `browser_exec` · `save_helper` ·
`list_helpers` · `load_helper` · `connect_chrome` · `fagun_security_prompt` ·
`list_external_security_tools` · `recommend_security_tools` · `close_browser`

**What's new in v0.7.0 — deeper, smarter, evidence-backed:**
- **`fuzz_forms`** — actively fills every form field with a labelled test-data
  catalog (valid / invalid / edge / boundary / out-of-box / injection) and reads
  the browser's *real* Constraint-Validation verdict. A validation gap is reported
  only when the browser itself accepted a value it should have rejected.
- **`perf_audit`** — real Core Web Vitals (LCP, CLS, TBT, FCP, TTFB) from the
  browser's Performance APIs + a Lighthouse-comparable 0-100 score. No estimates.
- **`a11y_audit`** — deep WCAG 2.1 checks incl. real computed color-contrast.
- **`advanced_security`** / bigger `security_scan` — CSP quality, clickjacking,
  risky HTTP methods, mixed content, missing SRI, sensitive-page caching, host-
  header injection, CRLF, path-traversal/LFI, SSTI, command-injection, GraphQL
  introspection, error/stack-trace disclosure, sensitive-data-in-URL.
- Every finding carries **evidence** — nothing is fabricated; unreproducible = not reported.

---

## 🛠️ For developers

```bash
git clone https://github.com/mejbaurbahar/fagun && cd fagun
pip install -e .
python -m playwright install chromium
python -m fagun        # runs the MCP server on stdio
```

**Release (maintainer):** publishing is automatic via GitHub Actions +
[PyPI Trusted Publishing](https://pypi.org/manage/account/publishing/). Bump the
version in `pyproject.toml` and `src/fagun/__init__.py`, then:

```bash
git tag v0.3.0 && git push origin v0.3.0
```

---

MIT © [Mejbaur Bahar Fagun](https://github.com/mejbaurbahar)
