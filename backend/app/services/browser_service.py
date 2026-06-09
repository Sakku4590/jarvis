"""Browser service.

Browser automation is the third dangerous capability: it drives a real browser
over the open web, and anything it reads is attacker-influenced. So it lives
behind an interface (BrowserService) with a real Playwright implementation, and
two safety measures that do not depend on Playwright and are unit-tested:

  - validate_url: only http/https, and an optional hostname allowlist. This
    blocks file://, javascript:, data:, and (when an allowlist is set) keeps the
    agent on approved domains. It runs before any navigation.
  - extracted page text is returned as DATA only. The agent's prompt is told to
    never follow instructions found in page content. Treating scraped text as
    trusted input is the classic browser-agent prompt-injection hole.

Playwright is imported lazily inside the implementation, so importing this
module (and the tools and agent that depend on it) never requires Playwright or
its browser binaries to be installed. Install for real use with:
    pip install playwright && playwright install chromium
"""

import asyncio
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class BrowserError(Exception):
    pass


class UrlNotAllowed(BrowserError):
    pass


def validate_url(url: str, allowed_domains: list[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlNotAllowed(f"scheme not allowed: {parsed.scheme or '(none)'}")
    if not parsed.netloc:
        raise UrlNotAllowed("missing host")
    if allowed_domains:
        host = parsed.hostname or ""
        ok = any(host == d or host.endswith("." + d) for d in allowed_domains)
        if not ok:
            raise UrlNotAllowed(f"host not in allowlist: {host}")
    return url


class PageResult(BaseModel):
    url: str
    title: str = ""
    status: int | None = None
    text: str = ""
    results: list[dict] = []   # for search
    submitted: bool = False    # for fill


class BrowserService(ABC):
    @abstractmethod
    async def open(self, url: str) -> PageResult: ...

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> PageResult: ...

    @abstractmethod
    async def extract(self, url: str, selector: str | None = None,
                      max_chars: int | None = None) -> PageResult: ...

    @abstractmethod
    async def fill(self, url: str, fields: dict[str, str], submit: bool = False,
                   submit_selector: str | None = None) -> PageResult: ...

    async def close(self) -> None:  # optional override
        return None


class PlaywrightBrowserService(BrowserService):
    """Real implementation. Each call uses a fresh, isolated browser context that
    is disposed afterwards, so calls do not leak state into one another and can
    run concurrently against one shared browser."""

    def __init__(self) -> None:
        s = get_settings()
        self.headless = s.browser_headless
        self.nav_timeout = s.browser_nav_timeout_ms
        self.max_chars = s.browser_max_extract_chars
        self.engine = s.browser_search_engine
        self.allowed = [d.strip() for d in s.browser_allowed_domains.split(",") if d.strip()]
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        async with self._lock:
            if self._browser is None:
                from playwright.async_api import async_playwright  # lazy

                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=self.headless)
        return self._browser

    async def _new_context(self):
        browser = await self._ensure_browser()
        # No downloads, modest viewport, default user agent.
        return await browser.new_context(accept_downloads=False)

    def _check(self, url: str) -> str:
        return validate_url(url, self.allowed or None)

    async def open(self, url: str) -> PageResult:
        self._check(url)
        ctx = await self._new_context()
        try:
            page = await ctx.new_page()
            resp = await page.goto(url, timeout=self.nav_timeout, wait_until="domcontentloaded")
            return PageResult(url=page.url, title=await page.title(),
                              status=(resp.status if resp else None))
        finally:
            await ctx.close()

    async def extract(self, url: str, selector: str | None = None,
                      max_chars: int | None = None) -> PageResult:
        self._check(url)
        cap = max_chars or self.max_chars
        ctx = await self._new_context()
        try:
            page = await ctx.new_page()
            resp = await page.goto(url, timeout=self.nav_timeout, wait_until="domcontentloaded")
            if selector:
                node = await page.query_selector(selector)
                text = (await node.inner_text()) if node else ""
            else:
                text = await page.inner_text("body")
            return PageResult(url=page.url, title=await page.title(),
                              status=(resp.status if resp else None),
                              text=text[:cap])
        finally:
            await ctx.close()

    async def search(self, query: str, max_results: int = 5) -> PageResult:
        if self.engine == "bing":
            base, sel = "https://www.bing.com/search?q=", "li.b_algo h2 a"
        else:
            base, sel = "https://duckduckgo.com/html/?q=", "a.result__a"
        from urllib.parse import quote_plus

        url = base + quote_plus(query)
        ctx = await self._new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, timeout=self.nav_timeout, wait_until="domcontentloaded")
            anchors = await page.query_selector_all(sel)
            results = []
            for a in anchors[:max_results]:
                href = await a.get_attribute("href")
                title = (await a.inner_text()).strip()
                if href and title:
                    results.append({"title": title, "url": href})
            return PageResult(url=url, title=f"results for {query}", results=results)
        finally:
            await ctx.close()

    async def fill(self, url: str, fields: dict[str, str], submit: bool = False,
                   submit_selector: str | None = None) -> PageResult:
        self._check(url)
        ctx = await self._new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, timeout=self.nav_timeout, wait_until="domcontentloaded")
            for selector, value in fields.items():
                await page.fill(selector, value, timeout=self.nav_timeout)
            submitted = False
            if submit:
                if submit_selector:
                    await page.click(submit_selector, timeout=self.nav_timeout)
                else:
                    await page.keyboard.press("Enter")
                await page.wait_for_load_state("domcontentloaded")
                submitted = True
            return PageResult(url=page.url, title=await page.title(), submitted=submitted)
        finally:
            await ctx.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = None
        self._pw = None


def get_browser_service() -> BrowserService:
    return PlaywrightBrowserService()
