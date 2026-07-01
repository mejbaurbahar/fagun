"""Entry point. `fagun` (or `uvx fagun`) starts the MCP server over stdio.

Env vars:
  FAGUN_HEADLESS   "0" to show the browser window (default "1" = headless)
  FAGUN_CDP_URL    connect to an already-running Chrome via CDP instead of
                   launching a fresh one, e.g. http://127.0.0.1:9222
  FAGUN_BROWSER    chromium | firefox | webkit  (default chromium)
"""

from __future__ import annotations

import sys


def main() -> None:
    # `fagun setup` — install the browser engine up front (also auto-runs on
    # first browser use, so this is optional but nice for a clean first launch).
    if len(sys.argv) > 1 and sys.argv[1] in {"setup", "--setup"}:
        import os

        from .browser import ensure_browser_installed

        engine = os.environ.get("FAGUN_BROWSER", "chromium").lower()
        print(f"Installing {engine} browser engine…")
        ensure_browser_installed(engine)
        print(f"✅ {engine} ready. Add fagun to your AI tool: `fagun install`")
        return

    # Support `fagun install` helper without importing the heavy MCP stack.
    if len(sys.argv) > 1 and sys.argv[1] in {"install", "--install", "help", "--help", "-h"}:
        from .install import run_cli

        run_cli(sys.argv[1:])
        return

    from .server import serve

    serve()


if __name__ == "__main__":
    main()
