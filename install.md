# Fagun — install & connect (for the AI agent to follow)

You are an AI coding tool (Claude, Cursor, Codex, Antigravity, Windsurf, Cline, …).
The user asked you to install and connect **Fagun**. Do the steps below in order.
If any step fails, read the "Troubleshooting" section and retry.

## Fastest path (try this first)

The entire setup is ONE command — installs the browser engine and registers Fagun
plus Chrome DevTools MCP into every AI tool it detects (Claude Code, Cursor,
Claude Desktop, Codex, Windsurf). It also opens Chrome's remote-debugging setup
page so the user can approve the official browser permission popup:

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
- Chrome DevTools MCP: **command `npx`, args `["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]`**

- **Claude Code:**
  ```bash
  claude mcp add fagun -- uvx fagun
  claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --auto-connect --no-usage-statistics
  ```
- **Cursor / Windsurf / Cline / Antigravity** — `~/.cursor/mcp.json` (or equivalent):
  ```json
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
- **VS Code (Copilot MCP)** — `.vscode/mcp.json`:
  ```json
  {
    "servers": {
      "fagun": { "type": "stdio", "command": "uvx", "args": ["fagun"] },
      "chrome-devtools": {
        "type": "stdio",
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
- **Codex CLI** — `~/.codex/config.toml`:
  ```toml
  [mcp_servers.fagun]
  command = "uvx"
  args = ["fagun"]

  [mcp_servers.chrome-devtools]
  command = "npx"
  args = ["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]
  env = { CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1", CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = "1" }
  startup_timeout_ms = 20_000
  ```

Shortcut — let Fagun write the file: `uvx fagun install cursor` (or `claude`, `vscode`).
For Chrome DevTools only: `uvx fagun install chrome-devtools`.

The `-y` flag prevents an `npx` confirmation prompt. `--auto-connect` makes Chrome
DevTools MCP attach to the user's running Chrome, so logged-in sessions can be
tested without asking for credentials. Fagun opens `chrome://inspect/#remote-debugging`;
the user should enable remote debugging and click **Allow** when Chrome shows the
permission modal.
Generated configs opt out of Chrome DevTools MCP usage statistics and update
checks. On Windows, Fagun writes Codex's documented `cmd /c npx ...` shape plus a
startup timeout automatically.

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
