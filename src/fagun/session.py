"""Authenticated-session persistence — test behind a login.

Fagun's biggest blind spot was auth-gated surface: dashboards, account pages,
checkout, anything past a login. This module saves the current browser session
(cookies + localStorage, via Playwright ``storage_state``) to disk and restores
it into a fresh context, so the flow is:

    1. run_journey / click+fill to log in once
    2. save_session("acme")            -> ~/.config/fagun/sessions/acme.json
    3. (next run or after a reset) load_session("acme")
    4. deep_test / crawl / security_scan now run AS the logged-in user

Restoring a session recreates the browser context, so it also clears any
persona throttling and stale listeners — a clean authenticated slate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .browser import manager


def _dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "fagun" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    s = "".join(c for c in name if c.isalnum() or c in "_-")
    return s or "default"


def _path(name: str) -> Path:
    return _dir() / f"{_safe(name)}.json"


def _summary(state: dict[str, Any]) -> str:
    cookies = len(state.get("cookies", []))
    origins = state.get("origins", [])
    ls = sum(len(o.get("localStorage", [])) for o in origins)
    return f"{cookies} cookie(s), {ls} localStorage item(s) across {len(origins)} origin(s)"


async def save_session(name: str) -> str:
    """Persist the current logged-in session to disk under ``name``."""
    path = _path(name)
    state = await manager.storage_state(path=str(path))
    if not state.get("cookies") and not state.get("origins"):
        return (f"⚠️ Saved '{_safe(name)}' but it holds no cookies/localStorage — "
                f"log in first, then save. → {path}")
    return f"✅ Saved session '{_safe(name)}' ({_summary(state)}) → {path}"


async def load_session(name: str) -> str:
    """Restore a saved session into a fresh browser context (auth applied)."""
    path = _path(name)
    if not path.exists():
        avail = ", ".join(list_session_names()) or "none"
        return f"No saved session '{_safe(name)}'. Available: {avail}"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Session '{_safe(name)}' is unreadable: {e}"
    await manager.new_context_with(storage_state=state)
    return f"✅ Loaded session '{_safe(name)}' ({_summary(state)}). Browser is now authenticated."


def list_session_names() -> list[str]:
    return sorted(p.stem for p in _dir().glob("*.json"))


def list_sessions() -> str:
    names = list_session_names()
    if not names:
        return "No saved sessions. Log in, then call save_session('name')."
    lines = ["Saved sessions:"]
    for n in names:
        try:
            state = json.loads(_path(n).read_text(encoding="utf-8"))
            lines.append(f"- {n}: {_summary(state)}")
        except Exception:
            lines.append(f"- {n}: (unreadable)")
    return "\n".join(lines)


def delete_session(name: str) -> str:
    path = _path(name)
    if path.exists():
        path.unlink()
        return f"Deleted session '{_safe(name)}'."
    return f"No session '{_safe(name)}' to delete."
