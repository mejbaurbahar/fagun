"""Entry point. `fagun` (or `uvx fagun`) starts the MCP server over stdio.

Env vars:
  FAGUN_HEADLESS   "0" to show the browser window (default "1" = headless)
  FAGUN_CDP_URL    connect to an already-running Chrome via CDP instead of
                   launching a fresh one, e.g. http://127.0.0.1:9222
  FAGUN_BROWSER    chromium | firefox | webkit  (default chromium)
  FAGUN_SCOPE      comma-separated hostnames Fagun is allowed to probe (incl.
                   subdomains). When set, any other host is refused — keeps
                   active security probes on authorized targets only.
  FAGUN_SCOPE_DENY comma-separated hostnames always refused, even if allowed.
"""

from __future__ import annotations

import sys


def main() -> None:
    # `fagun setup` — install the browser engine up front (also auto-runs on
    # first browser use, so this is optional but nice for a clean first launch).
    if len(sys.argv) > 1 and sys.argv[1] in {"setup", "--setup"}:
        import os

        from .browser import ensure_browser_installed
        from .install import _open_remote_debugging_setup

        engine = os.environ.get("FAGUN_BROWSER", "chromium").lower()
        print(f"Installing {engine} browser engine…")
        ensure_browser_installed(engine)
        print(f"✅ {engine} ready. Add fagun to your AI tool: `fagun install`")
        _open_remote_debugging_setup()
        return

    # `fagun connect-chrome` — launch a debuggable Chrome (no manual chrome://inspect).
    if len(sys.argv) > 1 and sys.argv[1] in {"connect-chrome", "chrome"}:
        from .browser import launch_debuggable_chrome

        port = int(sys.argv[2]) if len(sys.argv) > 2 else 9222
        cdp = launch_debuggable_chrome(port)
        print(f"✅ Chrome launched with remote debugging at {cdp}")
        print(f"   Fagun will attach automatically (FAGUN_CDP_URL={cdp}).")
        print("   Add to your MCP config env if you want this by default.")
        return

    # Support `fagun install` / `fagun init` helpers without the heavy MCP stack.
    if len(sys.argv) > 1 and sys.argv[1] in {
        "install", "--install", "init", "setup-all", "auto", "help", "--help", "-h"
    }:
        from .install import run_cli

        run_cli(sys.argv[1:])
        return

    from .server import serve

    serve()


if __name__ == "__main__":
    main()
