"""Playwright wrapper. One shared browser/context/page per server process.

Captures console messages and network requests as they happen so the QA tools
and the AI can inspect them at any time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


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
        if cdp:
            # Attach to an already-running Chrome (the "autoConnect" style flow).
            self._browser = await launcher.connect_over_cdp(cdp)
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
        else:
            if headless is None:
                headless = os.environ.get("FAGUN_HEADLESS", "1") != "0"
            self._browser = await launcher.launch(headless=headless)
            self._context = await self._browser.new_context()

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        self._wire_listeners(self._page)
        return f"Browser started ({engine}, {'CDP' if cdp else 'launched'})."

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
