"""Playwright wrapper. One shared browser/context/page per server process.

Captures console messages and network requests as they happen so the QA tools
and the AI can inspect them at any time.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


def ensure_browser_installed(engine: str = "chromium") -> None:
    """Install the Playwright browser engine if it isn't already present.

    Runs `python -m playwright install <engine>` once. Idempotent — Playwright
    skips the download if the browser is already cached. This is what makes
    Chrome setup fully automatic: the user never runs a separate install step.
    """
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", engine],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as e:  # pragma: no cover - surfaced to the caller's retry
        detail = getattr(e, "stderr", "") or str(e)
        raise RuntimeError(
            f"Automatic browser install failed for {engine}. "
            f"Run manually: {sys.executable} -m playwright install {engine}\n{detail}"
        ) from e


def _is_missing_browser_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "executable doesn't exist" in msg or "playwright install" in msg


def _find_chrome() -> Optional[str]:
    """Locate a real Chrome/Chromium binary per OS."""
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif sys.platform.startswith("win"):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = [
            rf"{pf}\Google\Chrome\Application\chrome.exe",
            rf"{pfx}\Google\Chrome\Application\chrome.exe",
            rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        ]
    else:
        import shutil

        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(name)
            if p:
                return p
        candidates = ["/usr/bin/google-chrome", "/usr/bin/chromium"]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def launch_debuggable_chrome(port: int = 9222) -> str:
    """Launch the user's real Chrome with remote debugging enabled, in a dedicated
    profile. This is the fully-automatic alternative to manually ticking
    chrome://inspect/#remote-debugging — no clicks needed. Sets FAGUN_CDP_URL so
    the next browser start attaches to it.
    """
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError(
            "No Chrome/Chromium found. Install Chrome, or launch it yourself with "
            f"--remote-debugging-port={port} and set FAGUN_CDP_URL=http://127.0.0.1:{port}"
        )
    profile = Path(
        os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    ) / "fagun" / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp = f"http://127.0.0.1:{port}"
    os.environ["FAGUN_CDP_URL"] = cdp
    return cdp


@dataclass
class NetworkEntry:
    method: str
    url: str
    status: Optional[int] = None
    resource_type: str = ""
    failure: Optional[str] = None


@dataclass
class ConsoleEntry:
    type: str
    text: str
    location: str = ""


@dataclass
class BrowserManager:
    _pw: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    console: list[ConsoleEntry] = field(default_factory=list)
    network: list[NetworkEntry] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def start(self, headless: Optional[bool] = None) -> str:
        if self.is_open:
            return f"Browser already open at {self._page.url or 'about:blank'}"

        self._pw = await async_playwright().start()
        engine = os.environ.get("FAGUN_BROWSER", "chromium").lower()
        launcher = {
            "chromium": self._pw.chromium,
            "firefox": self._pw.firefox,
            "webkit": self._pw.webkit,
        }.get(engine, self._pw.chromium)

        cdp = os.environ.get("FAGUN_CDP_URL")
        auto_installed = False
        if cdp:
            # Attach to an already-running Chrome (the "autoConnect" style flow).
            # Retry: a freshly-launched Chrome may take a second to open the port.
            import asyncio

            last: Exception | None = None
            for _ in range(15):
                try:
                    self._browser = await launcher.connect_over_cdp(cdp)
                    last = None
                    break
                except Exception as e:
                    last = e
                    await asyncio.sleep(0.5)
            if last is not None:
                raise RuntimeError(f"Could not connect to Chrome at {cdp}: {last}")
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
        else:
            if headless is None:
                headless = os.environ.get("FAGUN_HEADLESS", "1") != "0"
            try:
                self._browser = await launcher.launch(headless=headless)
            except Exception as e:
                # First run with no browser installed -> install it, then retry once.
                if not _is_missing_browser_error(e):
                    raise
                ensure_browser_installed(engine)
                auto_installed = True
                self._browser = await launcher.launch(headless=headless)
            self._context = await self._browser.new_context()

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        self._wire_listeners(self._page)
        note = " (auto-installed engine)" if auto_installed else ""
        return f"Browser started ({engine}, {'CDP' if cdp else 'launched'}){note}."

    def _wire_listeners(self, page: Page) -> None:
        def on_console(msg: Any) -> None:
            loc = msg.location or {}
            where = f"{loc.get('url', '')}:{loc.get('lineNumber', '')}"
            self.console.append(ConsoleEntry(msg.type, msg.text, where))

        def on_response(resp: Any) -> None:
            self.network.append(
                NetworkEntry(
                    method=resp.request.method,
                    url=resp.url,
                    status=resp.status,
                    resource_type=resp.request.resource_type,
                )
            )

        def on_request_failed(req: Any) -> None:
            self.network.append(
                NetworkEntry(
                    method=req.method,
                    url=req.url,
                    failure=(req.failure or "failed"),
                    resource_type=req.resource_type,
                )
            )

        page.on("console", on_console)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

    async def page(self) -> Page:
        if not self.is_open:
            await self.start()
        assert self._page is not None
        return self._page

    def clear_logs(self) -> None:
        self.console.clear()
        self.network.clear()

    async def stop(self) -> str:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._context = self._page = None
        self.clear_logs()
        return "Browser closed."


manager = BrowserManager()
