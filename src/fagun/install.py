"""`fagun install` — print copy-paste MCP config for each AI tool.

We only PRINT config (and offer to write Claude/Cursor JSON) so the user never
has to hand-edit blind. Every tool that speaks MCP can run Fagun with:

    command: uvx   args: ["fagun"]
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SERVER_BLOCK = {"command": "uvx", "args": ["fagun"]}

CLAUDE = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK}}, indent=2)
CURSOR = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK}}, indent=2)
VSCODE = json.dumps({"servers": {"fagun": {"type": "stdio", **SERVER_BLOCK}}}, indent=2)
CODEX = '[mcp_servers.fagun]\ncommand = "uvx"\nargs = ["fagun"]'

HELP = f"""🦊 Fagun install — add this MCP server to your AI tool, then say "fagun".

Prereqs (once):
  pip install uv           # gives you uvx
  uvx --from fagun python -m playwright install chromium   # browser engine

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
    elif target == "claude":
        _write_json_server(
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "mcpServers",
        )
    elif target == "vscode":
        _write_json_server(Path.cwd() / ".vscode" / "mcp.json", "servers")
    else:
        print(HELP)
