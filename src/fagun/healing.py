"""Self-healing helpers — the agent writes what's missing at runtime.

`browser_exec` runs async Python against the live page (full Playwright power), so
when a built-in tool can't do something, the AI just writes the code. `save_helper`
persists a working snippet to the workspace so next time it's a one-liner. This is
the browser-harness idea: a thin harness the agent improves every run.

⚠️ browser_exec runs arbitrary Python on THIS machine, against YOUR browser. It's
meant for the local automation you asked for — the same trust model as any browser
MCP. It never phones home.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import Any

from .browser import manager


def workspace() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "fagun" / "helpers"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def browser_exec(code: str) -> str:
    """Run async Python with `page`, `context`, `manager` in scope.

    Assign to `result` to return a value. Example:
        result = await page.title()
    """
    page = await manager.page()
    scope: dict[str, Any] = {
        "page": page,
        "context": manager._context,
        "manager": manager,
        "result": None,
    }
    # Append `return locals()` so an assigned `result` propagates out. An explicit
    # `return x` in the user code wins (the appended line is then unreachable).
    wrapped = (
        "async def __fagun_exec():\n"
        + textwrap.indent(code, "    ")
        + "\n    return locals()"
    )
    try:
        exec(compile(wrapped, "<browser_exec>", "exec"), scope)  # noqa: S102 - intentional
        out = await scope["__fagun_exec"]()
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
    if isinstance(out, dict):  # no explicit return -> locals()
        val = out.get("result")
    else:  # explicit `return x`
        val = out
    return repr(val)[:5000]


def save_helper(name: str, code: str) -> str:
    """Persist a reusable helper snippet to the workspace."""
    safe = "".join(c for c in name if c.isalnum() or c in "_-")
    path = workspace() / f"{safe}.py"
    path.write_text(code, encoding="utf-8")
    return f"Saved helper '{safe}' → {path}"


def list_helpers() -> str:
    files = sorted(workspace().glob("*.py"))
    if not files:
        return "No saved helpers yet."
    return "\n".join(f"- {f.stem}" for f in files)


def load_helper(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "_-")
    path = workspace() / f"{safe}.py"
    if not path.exists():
        return f"No helper named '{safe}'."
    return path.read_text(encoding="utf-8")
