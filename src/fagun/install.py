"""`fagun install` — print copy-paste MCP config for each AI tool.

We only PRINT config (and offer to write Claude/Cursor JSON) so the user never
has to hand-edit blind. Every tool that speaks MCP can run Fagun with:

    command: uvx   args: ["fagun"]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SERVER_BLOCK = {"command": "uvx", "args": ["fagun"]}

CLAUDE = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK}}, indent=2)
CURSOR = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK}}, indent=2)
VSCODE = json.dumps({"servers": {"fagun": {"type": "stdio", **SERVER_BLOCK}}}, indent=2)
CODEX = '[mcp_servers.fagun]\ncommand = "uvx"\nargs = ["fagun"]'

HELP = f"""🦊 Fagun install — add this MCP server to your AI tool, then say "fagun".

Prereqs (once) — no Python/pip needed, uv brings its own:
  macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
  Windows:      powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  then:         uvx fagun setup     # installs the Chrome engine automatically

────────────────────────────────────────────────────────────────────
Claude Code        →  run:  claude mcp add fagun -- uvx fagun
Claude Desktop     →  ~/Library/Application Support/Claude/claude_desktop_config.json
Cursor             →  ~/.cursor/mcp.json   (or .cursor/mcp.json in project)
Windsurf / Cline / Antigravity  →  their MCP settings, same JSON as Cursor
{CURSOR}

VS Code (Copilot MCP) →  .vscode/mcp.json
{VSCODE}

Codex CLI          →  ~/.codex/config.toml
{CODEX}
────────────────────────────────────────────────────────────────────
⚡ EASIEST — one command each (also installs the /fagun skill):
  uvx fagun install claude-code    # registers MCP in Claude Code (all projects)
  uvx fagun install cursor         # writes ~/.cursor/mcp.json
  uvx fagun install claude         # Claude Desktop
  uvx fagun install vscode         # .vscode/mcp.json
  uvx fagun install skill          # just the /fagun skill

🧩 Claude Code plugin (skill + MCP together):
  /plugin marketplace add mejbaurbahar/fagun
  /plugin install fagun@fagun
────────────────────────────────────────────────────────────────────
After adding: restart the tool, then type  fagun  to start.
"""


def _write_json_server(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            print(f"⚠️  {path} exists but is not valid JSON — skipped, add manually.")
            return
    data.setdefault(key, {})
    if key == "servers":
        data[key]["fagun"] = {"type": "stdio", **SERVER_BLOCK}
    else:
        data[key]["fagun"] = SERVER_BLOCK
    path.write_text(json.dumps(data, indent=2))
    print(f"✅ wrote fagun to {path}")


def run_cli(argv: list[str]) -> None:
    if not argv or argv[0] in {"help", "--help", "-h"}:
        print(HELP)
        return

    # `fagun install cursor` / `install claude` writes the file for you.
    target = argv[1] if len(argv) > 1 else ""
    home = Path.home()
    if target == "cursor":
        _write_json_server(home / ".cursor" / "mcp.json", "mcpServers")
        _install_skill(home / ".cursor" / "skills")
    elif target == "claude":
        _write_json_server(_claude_desktop_config_path(), "mcpServers")
        _install_skill(home / ".claude" / "skills")
    elif target == "vscode":
        _write_json_server(Path.cwd() / ".vscode" / "mcp.json", "servers")
    elif target in ("claude-code", "cc"):
        _install_claude_code()
        _install_skill(home / ".claude" / "skills")
    elif target == "skill":
        _install_skill(home / ".claude" / "skills")
    else:
        print(HELP)


def _install_skill(skills_dir: Path) -> None:
    """Copy the bundled /fagun skill into a tool's skills directory."""
    try:
        from importlib.resources import files

        text = (files("fagun.data") / "skill.md").read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️  could not load bundled skill: {e}")
        return
    dest = skills_dir / "fagun" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"✅ installed /fagun skill to {dest}")


def _install_claude_code() -> None:
    """Register the fagun MCP server in Claude Code (user scope), all projects."""
    import shutil
    import subprocess

    if not shutil.which("claude"):
        print("⚠️  `claude` CLI not found. Run manually: claude mcp add fagun --scope user -- uvx fagun")
        return
    try:
        subprocess.run(
            ["claude", "mcp", "add", "fagun", "--scope", "user", "--", "uvx", "fagun"],
            check=True,
        )
        print("✅ registered fagun in Claude Code (user scope). Restart Claude Code, then type: fagun")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  claude mcp add failed ({e}). It may already be registered — run `claude mcp list`.")


def _claude_desktop_config_path() -> Path:
    """Claude Desktop config path per OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"
