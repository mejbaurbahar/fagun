# Fagun — install & connect (for the AI agent to follow)

You are an AI coding tool (Claude, Cursor, Codex, Antigravity, Windsurf, Cline, …).
The user asked you to install and connect **Fagun**. Do the steps below in order.
If any step fails, read the "Troubleshooting" section and retry.

## Fastest path (try this first)

The entire setup is ONE command — installs the browser engine and registers Fagun
plus Chrome DevTools MCP into every AI tool it detects (Claude Code, Cursor,
Claude Desktop, Codex, Windsurf):

```bash
uvx fagun init
```

If `uv` is missing, install it first (macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`),
then re-run. If that works, you're done — skip the steps below.

## The command users give you

> Install or upgrade **fagun** to the latest stable version with `uv` using Python
> 3.12, register the skill from `fagun skill`, and connect it to my browser. Follow
> https://github.com/mejbaurbahar/fagun/blob/main/install.md if setup or connection
> fails.

## Step 1 — ensure `uv` exists (no Python/pip required — uv bundles its own)

Detect the OS and run the matching installer. `uv` provides its own Python, so the
user does NOT need pip or a system Python.

**macOS / Linux:**
```bash
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh
```
**Windows (PowerShell):**
```powershell
uv --version; if ($LASTEXITCODE -ne 0) { powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" }
```

After install, `uv` may not be on PATH until the shell restarts. In the current
shell you can source it (macOS/Linux): `source $HOME/.local/bin/env`. On Windows,
open a new terminal.

## Step 2 — install / upgrade Fagun with Python 3.12

```bash
uv tool install --python 3.12 --upgrade fagun
```

If `fagun` is not on PyPI yet, install from GitHub:

```bash
uv tool install --python 3.12 --upgrade "git+https://github.com/mejbaurbahar/fagun"
```

## Step 3 — install the browser engine

```bash
uvx fagun setup
```

(Optional — Fagun also auto-installs Chromium the first time it opens a browser,
so this step just makes the first launch instant.)

## Step 4 — register Fagun + Chrome DevTools MCP (pick the user's tool)

Fagun writes this automatically with `uvx fagun init`. Manual config uses:
- Fagun: **command `uvx`, args `["fagun"]`**
- Chrome DevTools MCP: **command `npx`, args `["-y", "chrome-devtools-mcp@latest"]`**

- **Claude Code:**
  ```bash
  claude mcp add fagun -- uvx fagun
  claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
  ```
- **Cursor / Windsurf / Cline / Antigravity** — `~/.cursor/mcp.json` (or equivalent):
  ```json
  {
    "mcpServers": {
      "fagun": { "command": "uvx", "args": ["fagun"] },
      "chrome-devtools": {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@latest"]
      }
    }
  }
  ```
- **VS Code (Copilot MCP)** — `.vscode/mcp.json`:
  ```json
  {
    "servers": {
      "fagun": { "type": "stdio", "command": "uvx", "args": ["fagun"] },
      "chrome-devtools": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@latest"]
      }
    }
  }
  ```
- **Codex CLI** — `~/.codex/config.toml`:
  ```toml
  [mcp_servers.fagun]
  command = "uvx"
  args = ["fagun"]

  [mcp_servers.chrome-devtools]
  command = "npx"
  args = ["-y", "chrome-devtools-mcp@latest"]
  ```

Shortcut — let Fagun write the file: `uvx fagun install cursor` (or `claude`, `vscode`).
For Chrome DevTools only: `uvx fagun install chrome-devtools`.

The `-y` flag prevents an `npx` confirmation prompt. Chrome DevTools MCP launches
its own dedicated Chrome profile by default, so the user does not need to open
`chrome://inspect` or manually enable remote debugging.

## Step 5 — register the skill

Copy `skills/fagun/SKILL.md` from this repo into the tool's skills directory
(e.g. `~/.claude/skills/fagun/SKILL.md`). This makes `/fagun` available as a
slash command. For tools without skills, the `fagun` MCP prompt is the entry point.

## Step 6 — connect to the browser & verify

Restart the AI tool, then call the `fagun_start` tool (or say `fagun`). Fagun
launches its own Chromium. To attach to an already-running Chrome instead, set:

```bash
export FAGUN_CDP_URL=http://127.0.0.1:9222   # Chrome started with --remote-debugging-port=9222
```

Verify: ask *"go to https://example.com and screenshot it"*.

## Troubleshooting

- **`uv` not found** → re-run Step 1, then `source ~/.bashrc` / open a new shell.
- **`playwright` browser missing / launch error** → re-run Step 3. On Linux add deps:
  `uv tool run --from fagun python -m playwright install-deps chromium`.
- **Tool doesn't see `fagun`** → fully restart the AI tool after editing MCP config;
  confirm the JSON is valid (no trailing commas).
- **Want to see the browser** → set `FAGUN_HEADLESS=0`.
- **Corporate proxy / SSL** → set `HTTPS_PROXY`; for CDP connect use `FAGUN_CDP_URL`.
- **Firefox/WebKit instead of Chrome** → `FAGUN_BROWSER=firefox` (run the matching
  `playwright install firefox` first).
