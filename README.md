# 🦊 Fagun

**Give any AI a browser and let it hunt real bugs for you.**

Fagun is a single tool that plugs into **Claude, Cursor, Codex, Antigravity, Windsurf,
Cline, or VS Code**. Once it's set up, you just type **`fagun`** (or `/fagun`) and your
AI can open a real browser, click around, and run a full quality check on any website —
finding broken links, console errors, failed requests, form problems, accessibility
issues, slow pages, and security misconfigurations.

You set it up **once**. It works in **every** AI tool. Chrome installs **itself**.

---

## ⚡ Fastest setup — pick one

**A) Paste this prompt into Claude Code / Cursor / Codex** — the AI does everything:

> Install and set up **fagun** for me: install `uv` if missing, run `uvx fagun setup`,
> then `uvx fagun install claude-code`. Follow
> https://github.com/mejbaurbahar/fagun/blob/main/install.md if anything fails.

**B) Claude Code plugin** — skill + browser tools in one go:

```
/plugin marketplace add mejbaurbahar/fagun
/plugin install fagun@fagun
```

**C) One command** (installs the MCP server **and** the `/fagun` skill):

```bash
uvx fagun install claude-code    # Claude Code (all projects)
uvx fagun install cursor         # Cursor
uvx fagun install claude         # Claude Desktop
uvx fagun install vscode         # VS Code
```

Then restart the tool and type **`fagun`**. That's it.

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

Every tool uses the **same** setting: run `uvx fagun`. Pick yours:

| Tool | How |
|------|-----|
| **Claude Code** | `claude mcp add fagun -- uvx fagun` |
| **Claude Desktop** | add the JSON below to `claude_desktop_config.json` |
| **Cursor** | `uvx fagun install cursor` (writes `~/.cursor/mcp.json`) |
| **VS Code (Copilot)** | `uvx fagun install vscode` (writes `.vscode/mcp.json`) |
| **Windsurf / Cline / Antigravity** | paste the JSON below into their MCP settings |
| **Codex CLI** | add the TOML below to `~/.codex/config.toml` |

```jsonc
// Claude Desktop / Cursor / Windsurf / Cline / Antigravity
{ "mcpServers": { "fagun": { "command": "uvx", "args": ["fagun"] } } }
```

```toml
# Codex — ~/.codex/config.toml
[mcp_servers.fagun]
command = "uvx"
args = ["fagun"]
```

**Restart the tool after adding it.** Then type `fagun`.

---

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
- **Reports go to disk, not context** — pass `report_path` and the full detail is
  written to a file while only a compact summary returns to the AI.

> 💡 Cheapest workflow: `deep test <url> and save the report to ./report.md`
> → one call, tiny summary in context, full report on disk.

## ⚙️ Options (optional)

Set these as environment variables if you need them:

| Variable | Default | What it does |
|----------|---------|--------------|
| `FAGUN_HEADLESS` | `1` | Set to `0` to **watch** the browser work |
| `FAGUN_BROWSER` | `chromium` | Use `firefox` or `webkit` instead |
| `FAGUN_CDP_URL` | — | Attach to **your own** open Chrome, e.g. `http://127.0.0.1:9222` |
| `FAGUN_TERSE` | `1` | Compact token-lean output. Set `0` for full JSON. |

---

## 🧰 Everything it can do (MCP tools)

`fagun_start` · `open_browser` · `navigate` · `click` · `fill` · `press_key` ·
`screenshot` · `evaluate_js` · `get_console` · `get_network` · `crawl` · `run_qa` ·
`check_links` · `test_forms` · `security_headers` · `deep_test` · `full_qa_sweep` ·
`write_report` · `close_browser`

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
