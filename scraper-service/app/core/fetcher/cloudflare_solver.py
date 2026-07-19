from __future__ import annotations

import time
import logging
from typing import Optional

from .base import FetchResult

logger = logging.getLogger(__name__)

CLOUDFLARE_MARKERS = [
    "cf-browser-verification",
    "cloudflare ray id",
    "checking your browser",
    "just a moment",
    "_cf_chl_opt",
]


def is_cloudflare_challenge(html: str) -> bool:
    lower = html.lower()
    return any(m in lower for m in CLOUDFLARE_MARKERS)


class PlaywrightCloudflareSolver:
    """Launches headless Chromium via Playwright to solve Cloudflare challenges.

    Should be used only as the last resort in the escalation chain,
    since it's expensive (browser launch + JS execution).
    """

    def __init__(self, headless: bool = True, solve_timeout_ms: int = 15_000):
        self._headless = headless
        self._solve_timeout_ms = solve_timeout_ms

    async def solve(self, url: str, user_agent: str | None = None) -> FetchResult:
        from playwright.async_api import async_playwright

        start = time.monotonic()
        logger.info("CloudflareSolver: launching playwright for %s", url)

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self._headless)
                context = await browser.new_context(
                    user_agent=user_agent or (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(self._solve_timeout_ms)
                html = await page.content()
                final_url = page.url
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
                await browser.close()

            elapsed_ms = (time.monotonic() - start) * 1000
            cf_clearance = cookies.get("cf_clearance", "")
            success = bool(cf_clearance) and not is_cloudflare_challenge(html)

            logger.info(
                "CloudflareSolver: %s (cf_clearance=%s) in %.0fms",
                "solved" if success else "failed",
                cf_clearance[:16] + "..." if cf_clearance else "none",
                elapsed_ms,
            )

            return FetchResult(
                url=url,
                status_code=200 if success else 403,
                content=html.encode("utf-8"),
                headers={},
                elapsed_ms=elapsed_ms,
                final_url=final_url,
                cookies=cookies,
                error=None if success else "Cloudflare challenge not solved",
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error("CloudflareSolver: exception %s", exc)
            return FetchResult(
                url=url,
                status_code=0,
                content=b"",
                headers={},
                elapsed_ms=elapsed_ms,
                final_url=url,
                error=f"CloudflareSolver failed: {exc}",
            )
