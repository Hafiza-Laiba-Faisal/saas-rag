"""
Playwright renderer — renders JS-heavy pages via headless Chromium.
Used for pages where Selenium is not needed (no cookie injection / login).
"""

from __future__ import annotations
import time
from .base import BaseRenderer, RenderResult
from config.settings import DEFAULT_USER_AGENT


class PlaywrightRenderer(BaseRenderer):
    """Stateless Playwright renderer — creates a fresh browser context per render."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw       = None
        self._browser  = None

    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self._headless)

    def render(
        self,
        url:         str,
        wait_ms:     int  = 3000,
        cookies:     dict | None = None,
        user_agent:  str  = DEFAULT_USER_AGENT,
        **kwargs,
    ) -> RenderResult:
        self._ensure_browser()
        start = time.monotonic()
        context = self._browser.new_context(user_agent=user_agent)
        try:
            if cookies:
                context.add_cookies([
                    {"name": k, "value": v, "domain": ".facebook.com", "path": "/"}
                    for k, v in cookies.items() if v
                ])
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(wait_ms)
            html = page.content()
            status = response.status if response else 200
            final_url = page.url
        finally:
            context.close()

        elapsed = (time.monotonic() - start) * 1000
        return RenderResult(
            url=url,
            html=html,
            status_code=status,
            final_url=final_url,
            elapsed_ms=round(elapsed, 2),
        )

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw      = None
