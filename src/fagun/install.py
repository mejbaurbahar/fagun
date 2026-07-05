"""`fagun install` — print copy-paste MCP config for each AI tool.

We only PRINT config (and offer to write Claude/Cursor JSON) so the user never
has to hand-edit blind. Every tool that speaks MCP can run Fagun with:

    command: uvx   args: ["fagun"]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable

SERVER_BLOCK = {"command": "uvx", "args": ["fagun"]}
REMOTE_DEBUGGING_SETUP_URL = "chrome://inspect/#remote-debugging"
CHROME_DEVTOOLS_ARGS = [
    "-y",
    "chrome-devtools-mcp@latest",
    "--auto-connect",
    "--no-usage-statistics",
]
CHROME_DEVTOOLS_ENV = {
    "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
    "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
}
CHROME_DEVTOOLS_BLOCK = {
    "command": "npx",
    "args": CHROME_DEVTOOLS_ARGS,
    "env": CHROME_DEVTOOLS_ENV,
}

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
args = ["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]
env = { CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1", CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = "1" }
startup_timeout_ms = 20_000"""

HELP = f"""🦊 Fagun install — add this MCP server to your AI tool, then say "fagun".

Recommended setup (no Python/pip needed, uv brings its own):
  macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
  Windows:      powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  then:         uvx fagun init      # browser + MCP + Chrome DevTools + /fagun skill

Prefer pip?
  pip install fagun
  fagun init

────────────────────────────────────────────────────────────────────
Claude Code        →  run:  claude mcp add fagun -- uvx fagun
                       claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --auto-connect --no-usage-statistics
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
chrome-devtools-mcp@latest --auto-connect --no-usage-statistics`, so Chrome
DevTools MCP connects to the user's running Chrome session. Setup opens
chrome://inspect/#remote-debugging so Chrome can show the official Allow remote
debugging permission popup on first attach.

After adding: restart the tool, then type  fagun  to start.
"""


_RULE = "━" * 60


def _short(path: Path) -> str:
    try:
        return "~/" + str(path.expanduser().resolve().relative_to(Path.home().resolve()))
    except Exception:
        return str(path)


def _ok(label: str, status: str = "Ready") -> str:
    return f"  ✓ {label:<30} {status}"


def _warn(label: str, status: str) -> str:
    return f"  ⚠ {label:<29} {status}"


def _err(label: str, status: str) -> str:
    return f"  ✗ {label:<30} {status}"


def _box(title: str, subtitle: str = "") -> str:
    width = 58
    lines = [
        "╭" + "─" * width + "╮",
        "│" + title.center(width) + "│",
    ]
    if subtitle:
        lines.append("│" + subtitle.center(width) + "│")
    lines.append("╰" + "─" * width + "╯")
    return "\n".join(lines)


def _section(title: str) -> None:
    print(f"\n{_RULE}\n{title}\n")


def _table(headers: tuple[str, str], rows: list[tuple[str, str, str]]) -> None:
    print(f"  {headers[0]:<30} {headers[1]}")
    print(f"  {'─' * 30} {'─' * 22}")
    for icon, name, status in rows:
        print(f"  {icon} {name:<28} {status}")


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
            raise RuntimeError(f"{_short(path)} is not valid JSON")
    data.setdefault(key, {})
    for name, block in (servers or _default_servers()).items():
        data[key][name] = _server_block_for(key, name, block)
    path.write_text(json.dumps(data, indent=2))


def _write_json_server(path: Path, key: str) -> None:
    _write_json_servers(path, key)


def _default_servers() -> dict[str, dict]:
    return {"fagun": SERVER_BLOCK, "chrome-devtools": CHROME_DEVTOOLS_BLOCK}


def _write_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chrome_block = _codex_chrome_devtools_block()
    blocks = {
        "fagun": '\n[mcp_servers.fagun]\ncommand = "uvx"\nargs = ["fagun"]\n',
        "chrome-devtools": chrome_block,
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = False
    for name, block in blocks.items():
        if f"[mcp_servers.{name}]" not in existing:
            existing += block
            changed = True
    if changed:
        path.write_text(existing, encoding="utf-8")


def init() -> None:
    """One command to rule them all: install the browser engine, then auto-detect
    every AI tool on this machine and register the fagun MCP server + /fagun skill.
    """
    import shutil

    home = Path.home()
    components: list[tuple[str, str, str]] = []
    files_written: list[Path] = []
    notes: list[str] = []
    connected: list[str] = []

    print(_box("🦊 FAGUN CLI", "AI testing platform setup"))
    _section("🚀 Current Task")
    print("  Initialize Fagun, browser automation, Chrome DevTools MCP, and AI tool skills.")
    _section("⏳ Progress")

    # 1. Browser engine.
    browser_status = "Ready"
    try:
        from .browser import ensure_browser_installed

        ensure_browser_installed("chromium")
        components.append(("✓", "Chromium browser", "Ready"))
    except Exception as e:
        browser_status = f"Failed: {type(e).__name__}"
        components.append(("✗", "Chromium browser", browser_status))
        notes.append(str(e))

    chrome_status = "Not found"
    if shutil.which("npx"):
        chrome_status = "Auto-connect ready"
        components.append(("✓", "Chrome DevTools MCP", "--auto-connect"))
        notes.append(_open_remote_debugging_setup())
    else:
        components.append(("⚠", "Chrome DevTools MCP", "Needs Node.js/npx"))

    wired = []
    skilled: set = set()  # dirs we've already dropped the skill into (avoid dupes)

    def skill_once(d: Path) -> None:
        key = str(d.resolve())
        if key not in skilled:
            files_written.append(_install_skill(d))
            skilled.add(key)

    def step(name: str, fn: Callable[[], list[Path] | Path | None]) -> None:
        """Run one tool's wiring; never let a failure abort the rest of init."""
        try:
            result = fn()
            if isinstance(result, Path):
                files_written.append(result)
            elif isinstance(result, list):
                files_written.extend(result)
            wired.append(name)
            connected.append(name)
            components.append(("✓", name, "Connected"))
        except Exception as e:
            components.append(("⚠", name, f"Skipped: {type(e).__name__}"))
            notes.append(str(e))

    # 2. Claude Code (CLI).
    if shutil.which("claude"):
        def _cc():
            status = _install_claude_code()
            chrome = _install_claude_code_chrome_devtools()
            notes.append(f"Claude Code: Fagun {status}; Chrome DevTools {chrome}")
            skill_once(home / ".claude" / "skills")
        step("Claude Code", _cc)

    # 3. Cursor.
    if (home / ".cursor").exists() or _app_exists("Cursor"):
        def _cur():
            path = home / ".cursor" / "mcp.json"
            _write_json_server(path, "mcpServers")
            files_written.append(path)
            skill_once(home / ".cursor" / "skills")
        step("Cursor", _cur)

    # 4. Claude Desktop.
    cd = _claude_desktop_config_path()
    if cd.parent.exists() or _app_exists("Claude"):
        def _cdt():
            _write_json_server(cd, "mcpServers")
            files_written.append(cd)
            skill_once(home / ".claude" / "skills")
        step("Claude Desktop", _cdt)

    # 5. Codex.
    if (home / ".codex").exists() or shutil.which("codex"):
        def _codex():
            path = home / ".codex" / "config.toml"
            _write_codex(path)
            files_written.append(path)
        step("Codex", _codex)

    # 6. Windsurf / Cline share Cursor-style config dirs.
    if (home / ".codeium").exists() or _app_exists("Windsurf"):
        def _windsurf():
            path = home / ".codeium" / "windsurf" / "mcp_config.json"
            _write_json_server(path, "mcpServers")
            files_written.append(path)
        step("Windsurf", _windsurf)

    reload_cmd = "open a new terminal window" if sys.platform.startswith("win") else "exec $SHELL   (or just open a new terminal)"

    _table(("Component", "Status"), components)
    _section("📂 Configuration Files")
    seen: set[str] = set()
    shown = False
    for path in files_written:
        short = _short(path)
        if short not in seen:
            print(f"  ✓ {short}")
            seen.add(short)
            shown = True
    if not shown:
        print("  ℹ No config files were written. Use a target install command below.")
    if notes:
        _section("ℹ Notes")
        for note in notes:
            if note:
                print(f"  • {note}")
    _section("🎯 Results")
    if wired:
        print("  ✓ Initialization Complete")
        print(f"  ✓ Connected: {', '.join(connected)}")
        print("  ✓ Ready to use")
        _section("🚀 Next Commands")
        print("  1. Restart your AI tool so it loads Fagun.")
        print(f"  2. Reload this terminal: {reload_cmd}")
        print("  3. In your AI tool, type one command:")
        print()
        print("  fagun deep test https://example.com")
        print("  fagun security scan https://example.com")
        print("  fagun check links on https://example.com")
        print("  fagun test the signup form on https://example.com")
        print("\n  Chrome DevTools MCP auto-connects during deep tests when available.")
    else:
        print("No AI tools detected automatically.\n")
        print("Run one of:")
        print("  uvx fagun install claude-code")
        print("  uvx fagun install cursor")
        print("  uvx fagun install claude")
        print("  uvx fagun install vscode")
    print(_RULE)


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
    files: list[Path] = []
    rows: list[tuple[str, str, str]] = []

    def finish(title: str) -> None:
        print(_box("🦊 FAGUN CLI", title))
        _section("🎯 Results")
        _table(("Component", "Status"), rows)
        if files:
            _section("📂 Configuration Files")
            seen: set[str] = set()
            for path in files:
                short = _short(path)
                if short not in seen:
                    print(f"  ✓ {short}")
                    seen.add(short)
        _section("🚀 Next Commands")
        print("  Restart your AI tool, then type:")
        print("  fagun deep test https://example.com")
        print(_RULE)

    if target == "cursor":
        path = home / ".cursor" / "mcp.json"
        _write_json_server(path, "mcpServers")
        files += [path, _install_skill(home / ".cursor" / "skills")]
        rows.append(("✓", "Cursor", "Configured"))
        finish("Cursor install")
    elif target == "claude":
        path = _claude_desktop_config_path()
        _write_json_server(path, "mcpServers")
        files += [path, _install_skill(home / ".claude" / "skills")]
        rows.append(("✓", "Claude Desktop", "Configured"))
        finish("Claude Desktop install")
    elif target == "vscode":
        path = Path.cwd() / ".vscode" / "mcp.json"
        _write_json_server(path, "servers")
        files.append(path)
        rows.append(("✓", "VS Code", "Configured"))
        finish("VS Code install")
    elif target in ("claude-code", "cc"):
        rows.append(("✓", "Claude Code", _install_claude_code()))
        rows.append(("✓", "Chrome DevTools MCP", _install_claude_code_chrome_devtools()))
        files.append(_install_skill(home / ".claude" / "skills"))
        finish("Claude Code install")
    elif target in ("chrome", "chrome-devtools"):
        files.extend(_install_chrome_devtools_only())
        rows.append(("✓", "Chrome DevTools MCP", "Configured"))
        rows.append(("ℹ", "Remote debugging", _open_remote_debugging_setup()))
        finish("Chrome DevTools install")
    elif target == "skill":
        files.append(_install_skill(home / ".claude" / "skills"))
        rows.append(("✓", "/fagun skill", "Installed"))
        finish("Skill install")
    else:
        print(HELP)


def _install_skill(skills_dir: Path) -> Path:
    """Copy the bundled /fagun skill into a tool's skills directory."""
    try:
        from importlib.resources import files

        text = (files("fagun.data") / "skill.md").read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"could not load bundled skill: {e}") from e
    dest = skills_dir / "fagun" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _install_claude_code() -> str:
    """Register the fagun MCP server in Claude Code (user scope), all projects.

    Robust across OSes: resolves the full `claude` path (on Windows it's a .cmd, so a
    bare name fails CreateProcess), captures output, and NEVER raises — a broken or
    missing CLI must not abort `fagun init`.
    """
    import shutil
    import subprocess

    claude = shutil.which("claude")
    if not claude:
        return "CLI not found"
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
            return "Registered"
        elif "already exists" in blob or "already" in blob:
            return "Already registered"
        else:
            return ((r.stderr or r.stdout).strip()[:100] or "Skipped")
    except Exception as e:
        return f"Skipped: {type(e).__name__}"


def _run_cli_mcp_add(cli_name: str, server_name: str, command: list[str]) -> str:
    import shutil
    import subprocess

    cli = shutil.which(cli_name)
    if not cli:
        return "CLI not found"
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
        return "Registered"
    elif "already exists" in blob or "already" in blob:
        return "Already registered"
    else:
        return (r.stderr or r.stdout).strip()[:120] or "Skipped"


def _install_claude_code_chrome_devtools() -> str:
    """Register Chrome DevTools MCP in Claude Code with zero install prompts."""
    return _run_cli_mcp_add("claude", "chrome-devtools", ["npx", *CHROME_DEVTOOLS_ARGS])


def _open_remote_debugging_setup() -> str:
    """Open Chrome's official remote-debugging setup page.

    Chrome DevTools MCP `--auto-connect` intentionally requires the user to allow
    remote debugging in Chrome. Opening this page mirrors browser-harness setup:
    the user can tick the setting, and Chrome 144+ will show the Allow popup on
    first attach.
    """
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-a", "Google Chrome", REMOTE_DEBUGGING_SETUP_URL],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform.startswith("win"):
            os.startfile(REMOTE_DEBUGGING_SETUP_URL)  # type: ignore[attr-defined]
        else:
            chrome = _which_first("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
            if chrome:
                subprocess.Popen([chrome, REMOTE_DEBUGGING_SETUP_URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(REMOTE_DEBUGGING_SETUP_URL)
        return "Opened chrome://inspect/#remote-debugging"
    except Exception as e:
        return f"Open manually: {REMOTE_DEBUGGING_SETUP_URL} ({type(e).__name__})"


def _which_first(*names: str) -> str | None:
    import shutil

    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _codex_chrome_devtools_block() -> str:
    if sys.platform.startswith("win"):
        return (
            '\n[mcp_servers.chrome-devtools]\n'
            'command = "cmd"\n'
            'args = ["/c", "npx", "-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]\n'
            'env = { SystemRoot = "C:\\\\Windows", PROGRAMFILES = "C:\\\\Program Files", '
            'CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1", CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = "1" }\n'
            "startup_timeout_ms = 20_000\n"
        )
    return (
        '\n[mcp_servers.chrome-devtools]\n'
        'command = "npx"\n'
        'args = ["-y", "chrome-devtools-mcp@latest", "--auto-connect", "--no-usage-statistics"]\n'
        'env = { CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS = "1", CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS = "1" }\n'
        "startup_timeout_ms = 20_000\n"
    )


def _install_chrome_devtools_only() -> list[Path]:
    """Install only Chrome DevTools MCP into detected JSON/TOML MCP configs."""
    home = Path.home()
    files: list[Path] = []
    if (home / ".cursor").exists() or _app_exists("Cursor"):
        path = home / ".cursor" / "mcp.json"
        _write_json_servers(
            path,
            "mcpServers",
            {"chrome-devtools": CHROME_DEVTOOLS_BLOCK},
        )
        files.append(path)
    cd = _claude_desktop_config_path()
    if cd.parent.exists() or _app_exists("Claude"):
        _write_json_servers(cd, "mcpServers", {"chrome-devtools": CHROME_DEVTOOLS_BLOCK})
        files.append(cd)
    if (home / ".codex").exists():
        path = home / ".codex" / "config.toml"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if "[mcp_servers.chrome-devtools]" not in existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(existing + _codex_chrome_devtools_block(), encoding="utf-8")
        files.append(path)
    _install_claude_code_chrome_devtools()
    return files


def _claude_desktop_config_path() -> Path:
    """Claude Desktop config path per OS."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(base) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"
