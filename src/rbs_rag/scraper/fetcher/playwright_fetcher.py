"""Playwright-based fetcher with full JS rendering and Cloudflare bypass."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from rbs_rag.scraper.fetcher.http_fetcher import FetchResult
from rbs_rag.scraper.config import ScraperConfig, get_config
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class PlaywrightFetcher:
    """Async fetcher using Playwright for JS rendering and aggressive anti-bot bypass."""

    def __init__(self, config: ScraperConfig = None):
        self.config = config or get_config()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._initialized = False

    async def start(self):
        if self._initialized:
            return self
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            permissions=[],
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
        )
        await self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """
        )
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        self._initialized = True
        return self

    async def close(self):
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._initialized = False

    async def fetch(self, url: str) -> FetchResult:
        if not self._initialized:
            await self.start()

        async with self._semaphore:
            page: Optional[Page] = None
            try:
                page = await self._context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.request_timeout * 1000)
                await asyncio.sleep(1)

                content = await page.content()
                final_url = page.url
                headers = {}

                return FetchResult(
                    url=final_url or url,
                    status_code=200,
                    content=content.encode("utf-8"),
                    content_type="text/html",
                    headers=headers,
                )
            except Exception as e:
                logger.warning("Playwright fetch failed for %s: %s", url, e)
                return FetchResult(
                    url=url, status_code=0, content=b"", content_type="", headers={}, error=str(e)
                )
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
