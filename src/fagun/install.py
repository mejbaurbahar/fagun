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
CHROME_DEVTOOLS_BLOCK = {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"]}

CLAUDE = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK, "chrome-devtools": CHROME_DEVTOOLS_BLOCK}}, indent=2)
CURSOR = json.dumps({"mcpServers": {"fagun": SERVER_BLOCK, "chrome-devtools": CHROME_DEVTOOLS_BLOCK}}, indent=2)
VSCODE = json.dumps({
    "servers": {
        "fagun": {"type": "stdio", **SERVER_BLOCK},
        "chrome-devtools": {"type": "stdio", **CHROME_DEVTOOLS_BLOCK},
    }
}, indent=2)
CODEX = """[mcp_servers.fagun]
command = "uvx"
args = ["fagun"]

[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest"]"""

HELP = f"""🦊 Fagun install — add this MCP server to your AI tool, then say "fagun".

Prereqs (once) — no Python/pip needed, uv brings its own:
  macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
  Windows:      powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  then:         uvx fagun setup     # installs the Chrome engine automatically

────────────────────────────────────────────────────────────────────
Claude Code        →  run:  claude mcp add fagun -- uvx fagun
                       claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
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
Fagun also registers Chrome DevTools MCP automatically. It uses `npx -y
chrome-devtools-mcp@latest`, so Chrome DevTools can launch its own dedicated
Chrome profile without user-side chrome://inspect setup.

After adding: restart the tool, then type  fagun  to start.
"""


def _server_block_for(key: str, name: str, block: dict) -> dict:
    if key == "servers":
        return {"type": "stdio", **block}
    return block


def _write_json_servers(path: Path, key: str, servers: dict[str, dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            print(f"⚠️  {path} exists but is not valid JSON — skipped, add manually.")
            return
    data.setdefault(key, {})
    for name, block in (servers or _default_servers()).items():
        data[key][name] = _server_block_for(key, name, block)
    path.write_text(json.dumps(data, indent=2))
    print(f"✅ wrote fagun + Chrome DevTools MCP to {path}")


def _write_json_server(path: Path, key: str) -> None:
    _write_json_servers(path, key)


def _default_servers() -> dict[str, dict]:
    return {"fagun": SERVER_BLOCK, "chrome-devtools": CHROME_DEVTOOLS_BLOCK}


def _write_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = {
        "fagun": '\n[mcp_servers.fagun]\ncommand = "uvx"\nargs = ["fagun"]\n',
        "chrome-devtools": (
            '\n[mcp_servers.chrome-devtools]\n'
            'command = "npx"\n'
            'args = ["-y", "chrome-devtools-mcp@latest"]\n'
        ),
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = False
    for name, block in blocks.items():
        if f"[mcp_servers.{name}]" not in existing:
            existing += block
            changed = True
    if changed:
        path.write_text(existing, encoding="utf-8")
        print(f"✅ wrote fagun + Chrome DevTools MCP to {path}")
    else:
        print(f"✅ fagun + Chrome DevTools MCP already in {path}")


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

    if shutil.which("npx"):
        print("• Chrome DevTools MCP ready via npx -y chrome-devtools-mcp@latest")
    else:
        print("• Chrome DevTools MCP needs Node.js/npx on PATH — install Node.js, then rerun `uvx fagun init`")

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
            _install_claude_code_chrome_devtools()
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

    reload_cmd = "open a new terminal window" if sys.platform.startswith("win") else "exec $SHELL   (or just open a new terminal)"

    print("\n" + ("─" * 56))
    if wired:
        print("✅ Wired up: " + ", ".join(wired))
        print("\n▶ NEXT STEPS")
        print("  1. Restart your AI tool (quit & reopen it) so it loads Fagun.")
        print(f"  2. Reload this terminal:  {reload_cmd}")
        print("  3. In your AI tool, just type  fagun  then what to test, e.g.:")
        print("       fagun deep test https://example.com")
        print("       fagun security scan https://example.com")
        print("       fagun check links on https://example.com")
        print("       fagun connect to my Chrome")
        print("       fagun test the signup form on https://example.com")
    else:
        print("No AI tools detected automatically. Run one of:")
        print("   uvx fagun install claude-code | cursor | claude | vscode")
    print("─" * 56)


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
        _install_claude_code_chrome_devtools()
        _install_skill(home / ".claude" / "skills")
    elif target in ("chrome", "chrome-devtools"):
        _install_chrome_devtools_only()
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


def _run_cli_mcp_add(cli_name: str, server_name: str, command: list[str]) -> None:
    import shutil
    import subprocess

    cli = shutil.which(cli_name)
    if not cli:
        print(f"• {cli_name} CLI not found — skipped {server_name}")
        return
    args = [cli, "mcp", "add", server_name, "--scope", "user", "--", *command]
    win = sys.platform.startswith("win")
    r = subprocess.run(
        subprocess.list2cmdline(args) if win else args,
        capture_output=True,
        text=True,
        shell=win,
    )
    blob = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode == 0:
        print(f"✅ registered {server_name} in {cli_name} (user scope)")
    elif "already exists" in blob or "already" in blob:
        print(f"✅ {server_name} already registered in {cli_name}")
    else:
        detail = (r.stderr or r.stdout).strip()[:120] or "skipped"
        print(f"• {cli_name}: {detail} (run `{cli_name} mcp list` to check)")


def _install_claude_code_chrome_devtools() -> None:
    """Register Chrome DevTools MCP in Claude Code with zero install prompts."""
    _run_cli_mcp_add("claude", "chrome-devtools", ["npx", "-y", "chrome-devtools-mcp@latest"])


def _install_chrome_devtools_only() -> None:
    """Install only Chrome DevTools MCP into detected JSON/TOML MCP configs."""
    home = Path.home()
    if (home / ".cursor").exists() or _app_exists("Cursor"):
        _write_json_servers(
            home / ".cursor" / "mcp.json",
            "mcpServers",
            {"chrome-devtools": CHROME_DEVTOOLS_BLOCK},
        )
    cd = _claude_desktop_config_path()
    if cd.parent.exists() or _app_exists("Claude"):
        _write_json_servers(cd, "mcpServers", {"chrome-devtools": CHROME_DEVTOOLS_BLOCK})
    if (home / ".codex").exists():
        path = home / ".codex" / "config.toml"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if "[mcp_servers.chrome-devtools]" not in existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                existing
                + '\n[mcp_servers.chrome-devtools]\n'
                  'command = "npx"\n'
                  'args = ["-y", "chrome-devtools-mcp@latest"]\n',
                encoding="utf-8",
            )
            print(f"✅ wrote Chrome DevTools MCP to {path}")
    _install_claude_code_chrome_devtools()


def _claude_desktop_config_path() -> Path:
    """Claude Desktop config path per OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"
