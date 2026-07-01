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
🚀 ONE COMMAND — sets up EVERYTHING (browser + all detected AI tools + skill):
  uvx fagun init

⚡ Or target one tool (also installs the /fagun skill):
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


def _write_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    block = '\n[mcp_servers.fagun]\ncommand = "uvx"\nargs = ["fagun"]\n'
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "[mcp_servers.fagun]" in existing:
        print(f"✅ fagun already in {path}")
        return
    path.write_text(existing + block, encoding="utf-8")
    print(f"✅ wrote fagun to {path}")


def init() -> None:
    """One command to rule them all: install the browser engine, then auto-detect
    every AI tool on this machine and register the fagun MCP server + /fagun skill.
    """
    import shutil

    home = Path.home()
    print("🦊 Fagun init — setting up everything…\n")

    # 1. Browser engine.
    try:
        from .browser import ensure_browser_installed

        print("• Installing Chromium engine…")
        ensure_browser_installed("chromium")
        print("  ✅ browser ready")
    except Exception as e:
        print(f"  ⚠️  browser install failed: {e}")

    wired = []
    skilled: set = set()  # dirs we've already dropped the skill into (avoid dupes)

    def skill_once(d: Path) -> None:
        key = str(d.resolve())
        if key not in skilled:
            _install_skill(d)
            skilled.add(key)

    def step(name: str, fn) -> None:
        """Run one tool's wiring; never let a failure abort the rest of init."""
        try:
            fn()
            wired.append(name)
        except Exception as e:
            print(f"• {name} skipped ({type(e).__name__}: {e})")

    # 2. Claude Code (CLI).
    if shutil.which("claude"):
        def _cc():
            _install_claude_code()
            skill_once(home / ".claude" / "skills")
        step("Claude Code", _cc)

    # 3. Cursor.
    if (home / ".cursor").exists() or _app_exists("Cursor"):
        def _cur():
            _write_json_server(home / ".cursor" / "mcp.json", "mcpServers")
            skill_once(home / ".cursor" / "skills")
        step("Cursor", _cur)

    # 4. Claude Desktop.
    cd = _claude_desktop_config_path()
    if cd.parent.exists() or _app_exists("Claude"):
        def _cdt():
            _write_json_server(cd, "mcpServers")
            skill_once(home / ".claude" / "skills")
        step("Claude Desktop", _cdt)

    # 5. Codex.
    if (home / ".codex").exists() or shutil.which("codex"):
        step("Codex", lambda: _write_codex(home / ".codex" / "config.toml"))

    # 6. Windsurf / Cline share Cursor-style config dirs.
    if (home / ".codeium").exists() or _app_exists("Windsurf"):
        step("Windsurf", lambda: _write_json_server(
            home / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"))

    print("\n" + ("─" * 52))
    if wired:
        print("✅ Wired up: " + ", ".join(wired))
        print("   Restart the tool, then type:  fagun   (or /fagun)")
    else:
        print("No AI tools detected automatically. Run one of:")
        print("   uvx fagun install claude-code | cursor | claude | vscode")
    print("─" * 52)


def _app_exists(name: str) -> bool:
    if sys.platform == "darwin":
        return Path(f"/Applications/{name}.app").exists()
    return False


def run_cli(argv: list[str]) -> None:
    if not argv or argv[0] in {"help", "--help", "-h"}:
        print(HELP)
        return

    if argv[0] in {"init", "setup-all", "auto"}:
        init()
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
    """Register the fagun MCP server in Claude Code (user scope), all projects.

    Robust across OSes: resolves the full `claude` path (on Windows it's a .cmd, so a
    bare name fails CreateProcess), captures output, and NEVER raises — a broken or
    missing CLI must not abort `fagun init`.
    """
    import shutil
    import subprocess

    claude = shutil.which("claude")
    if not claude:
        print("• Claude Code CLI not found — skipped (run `claude mcp add fagun --scope user -- uvx fagun` if you use it)")
        return
    try:
        args = [claude, "mcp", "add", "fagun", "--scope", "user", "--", "uvx", "fagun"]
        # On Windows the resolved binary is a .cmd/.bat, which CreateProcess can't
        # exec directly by list form — run through the shell there.
        win = sys.platform.startswith("win")
        r = subprocess.run(
            subprocess.list2cmdline(args) if win else args,
            capture_output=True,
            text=True,
            shell=win,
        )
        blob = ((r.stdout or "") + (r.stderr or "")).lower()
        if r.returncode == 0:
            print("✅ registered fagun in Claude Code (user scope)")
        elif "already exists" in blob or "already" in blob:
            print("✅ fagun already registered in Claude Code")
        else:
            print(f"• Claude Code: {(r.stderr or r.stdout).strip()[:100] or 'skipped'} (run `claude mcp list` to check)")
    except Exception as e:
        print(f"• Claude Code register skipped ({type(e).__name__}). Run: claude mcp add fagun --scope user -- uvx fagun")


def _claude_desktop_config_path() -> Path:
    """Claude Desktop config path per OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"
