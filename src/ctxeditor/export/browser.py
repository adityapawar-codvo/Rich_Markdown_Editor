"""A shared headless Chromium for exports. Started lazily, kept warm, restarted if it dies, and limited to two
concurrent pages. Pages get no network: only the local document, the editor's rendering bundle and the self-hosted
fonts are served; every other request is aborted. The document HTML is sanitized and contains no script; the only
JavaScript that runs is our own bundle."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from ..errors import EditorError

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DIST = HERE.parent / "web" / "editor" / "dist"
STATIC = HERE.parent / "web" / "static"
ORIGIN = "http://ctx.local"
MAX_PAGES = 2
PAGE_TIMEOUT_MS = 30_000


class ExportFailed(EditorError):
    message = "The export could not be created. Please try again."


class BrowserPool:
    def __init__(self, max_pages: int = MAX_PAGES):
        self._slots = asyncio.Semaphore(max_pages)
        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None

    async def _ensure(self):
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch()
            except Exception:
                log.exception("export browser failed to start")
                raise ExportFailed("The export browser is not installed. Run: playwright install chromium") from None
            return self._browser

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    @asynccontextmanager
    async def page(self, document_html: str, *, scale: float = 2) -> AsyncIterator:
        """A page already loaded with document_html at ORIGIN/doc. Waits for window.__renderDone."""
        async with self._slots:
            browser = await self._ensure()
            context = await browser.new_context(device_scale_factor=scale, java_script_enabled=True,
                                                viewport={"width": 900, "height": 1200}, accept_downloads=False)
            try:
                async def serve(route):
                    url = route.request.url
                    if url == f"{ORIGIN}/doc":
                        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=document_html)
                        return
                    for prefix, root in (("/dist/", DIST), ("/static/", STATIC)):
                        path = url.removeprefix(ORIGIN)
                        if url.startswith(ORIGIN) and path.startswith(prefix):
                            target = (root / path.removeprefix(prefix).split("?")[0]).resolve()
                            if root.resolve() in target.parents and target.is_file():
                                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                                if target.suffix == ".js":
                                    ctype = "text/javascript"
                                await route.fulfill(status=200, content_type=ctype, body=target.read_bytes())
                                return
                    await route.abort()

                await context.route("**/*", serve)
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                try:
                    await page.goto(f"{ORIGIN}/doc", wait_until="load")
                    await page.wait_for_function("window.__renderDone === true")
                except Exception:
                    log.exception("export page failed to render")
                    raise ExportFailed() from None
                yield page
            finally:
                await context.close()
