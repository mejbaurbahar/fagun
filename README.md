# 🦊 Fagun

**One MCP server. Every AI tool. Type `fagun` and it drives a browser + runs full QA.**

Fagun is an [MCP](https://modelcontextprotocol.io) server that lets any AI coding
tool — **Claude Code / Desktop, Cursor, Codex, Antigravity, Windsurf, Cline, VS Code** —
control a real browser, debug it (console, network, DOM, screenshots, JS eval), and
run an automated quality sweep (broken requests, console errors, accessibility,
performance, SEO) with a Markdown report.

You set it up once. Then inside any of those tools you just say **`fagun`** (or `/fagun`) and it starts.

---

## One-line setup (paste into your AI tool)

Tell your AI agent (Claude, Cursor, Codex, Antigravity, …) exactly this:

> Install or upgrade **fagun** to the latest stable version with `uv` using Python
> 3.12, register the skill from `fagun skill`, and connect it to my browser. Follow
> https://github.com/mejbaurbahar/fagun/blob/main/install.md if setup or connection fails.

The agent follows [`install.md`](install.md) and wires everything up. Then just type
**`/fagun`** and describe what to test.

---

## Setup (once, ~2 min)

**1. Install the runner + browser engine**

```bash
pip install uv
uvx --from fagun python -m playwright install chromium
```

`uvx` runs Fagun without a permanent install and always uses the latest version.

**2. Add Fagun to your AI tool**

Print ready-to-paste config for every tool:

```bash
uvx fagun install
```

Or let Fagun write the file for you:

```bash
uvx fagun install cursor     # writes ~/.cursor/mcp.json
uvx fagun install claude     # writes Claude Desktop config
uvx fagun install vscode     # writes .vscode/mcp.json
```

Manual config is identical everywhere — command `uvx`, args `["fagun"]`:

| Tool | Where |
|------|-------|
| **Claude Code** | `claude mcp add fagun -- uvx fagun` |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Cursor** | `~/.cursor/mcp.json` |
| **Windsurf / Cline / Antigravity** | their MCP settings (same JSON as Cursor) |
| **VS Code (Copilot)** | `.vscode/mcp.json` |
| **Codex CLI** | `~/.codex/config.toml` |

```jsonc
// Claude Desktop / Cursor / Windsurf / Cline / Antigravity
{ "mcpServers": { "fagun": { "command": "uvx", "args": ["fagun"] } } }
```

```toml
# Codex ~/.codex/config.toml
[mcp_servers.fagun]
command = "uvx"
args = ["fagun"]
```

**3. Restart the tool. Say `fagun`.**

---

## Use it

Inside any tool, just talk:

- *"fagun"* → shows the menu and starts up
- *"go to example.com and screenshot it"*
- *"run QA on https://example.com"*
- *"full QA sweep of https://example.com, write the report to ./qa.md"*
- *"show me the console errors"* · *"any failed network requests?"*
- *"click Sign in, type me@x.com into email, press Enter"*

- *"deep test https://example.com and write the report to ./report.md"* — the full sweep

## The `/fagun` skill — autonomous bug hunter

`skills/fagun/SKILL.md` is a full QA methodology the AI follows: it hunts **real,
reproducible** bugs across 10 scenario classes — functional, JS/runtime errors,
network/API, form validation, auth/session/authorization, accessibility,
performance, visual/responsive, security posture, and edge cases — with an
evidence-or-it-didn't-happen rule and impact-based severity. Register it (see
`install.md` Step 5) to get the `/fagun` slash command.

## What it exposes (MCP tools)

`fagun_start` · `open_browser` · `navigate` · `click` · `fill` · `press_key` ·
`screenshot` · `evaluate_js` · `get_console` · `get_network` · `crawl` · `run_qa` ·
`check_links` · `test_forms` · `security_headers` · `deep_test` · `full_qa_sweep` ·
`write_report` · `close_browser`

Plus a **`fagun` prompt** — appears as a slash command in tools that surface MCP prompts.

## Options (env vars)

| Var | Default | Meaning |
|-----|---------|---------|
| `FAGUN_HEADLESS` | `1` | `0` shows the browser window |
| `FAGUN_BROWSER` | `chromium` | `chromium` \| `firefox` \| `webkit` |
| `FAGUN_CDP_URL` | — | Attach to a running Chrome, e.g. `http://127.0.0.1:9222` |

## Local dev

```bash
git clone <repo> && cd fagun
pip install -e .
python -m playwright install chromium
python -m fagun        # starts the MCP server on stdio
```

## Releasing to PyPI (maintainer)

Auto-publish is wired via GitHub Actions using **PyPI Trusted Publishing** (OIDC —
no API token stored). One-time setup on [pypi.org](https://pypi.org/manage/account/publishing/):

- Project: `fagun` · Owner: `mejbaurbahar` · Repo: `fagun`
- Workflow: `publish.yml` · Environment: `pypi`

Then every release is just a tag:

```bash
# bump version in pyproject.toml + src/fagun/__init__.py first
git tag v0.2.0 && git push origin v0.2.0
```

The `Publish to PyPI` workflow builds, checks, and uploads automatically. Build
locally to verify anytime: `python -m build && twine check dist/*`.

MIT © Mejbaur Bahar Fagun
