from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .base import FetchResult
from .async_httpx_fetcher import AsyncHttpxFetcher
from .cloudflare_solver import PlaywrightCloudflareSolver, is_cloudflare_challenge
from core.cache.memory_cache import cf_cache

logger = logging.getLogger(__name__)

_BOT_BLOCK_CODES = {403, 429, 503}


class EscalatingFetcher:
    """Async fetcher with an escalation chain:

    1. AsyncHttpxFetcher  — fastest, works for 99% of sites
    2. CurlCffiFetcher    — TLS fingerprint impersonation (wrapped via thread)
    3. PlaywrightSolver   — full browser render for Cloudflare JS challenges

    Per-domain cf_clearance cookies are cached for N minutes so repeated
    requests to the same domain don't re-launch the browser.
    """

    def __init__(
        self,
        cf_cache_ttl_sec: int = 1200,
        cf_solve_timeout_ms: int = 15_000,
        user_agent: Optional[str] = None,
    ):
        self._httpx = AsyncHttpxFetcher()
        self._solver = PlaywrightCloudflareSolver(solve_timeout_ms=cf_solve_timeout_ms)
        self._cf_cache_ttl = cf_cache_ttl_sec
        self._user_agent = user_agent

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        timeout: int = 30,
        **kwargs,
    ) -> FetchResult:
        result = await self._httpx.fetch(url, method=method, headers=headers, timeout=timeout, **kwargs)
        if result.ok:
            return result

        if result.status_code not in _BOT_BLOCK_CODES:
            return result

        content_text = result.text if result.content else ""
        if not is_cloudflare_challenge(content_text):
            cf_retry = await self._try_curl_cffi(url, method, headers, timeout, cookies=None)
            if cf_retry.ok:
                return cf_retry
            return result

        domain = _extract_domain(url)
        cached = cf_cache.get(domain)
        if cached:
            logger.info("EscalatingFetcher: reusing cached cf_clearance for %s", domain)
            cf_retry = await self._try_curl_cffi(url, method, headers, timeout, cookies=cached)
            if cf_retry.ok:
                return cf_retry
            if not is_cloudflare_challenge(cf_retry.text if cf_retry.content else ""):
                return cf_retry
            logger.info("EscalatingFetcher: cached cf_clearance expired for %s, re-solving", domain)

        solved = await self._solver.solve(url, user_agent=self._user_agent)
        if solved.ok and solved.cookies.get("cf_clearance"):
            cf_cache.set(domain, solved.cookies, ttl_seconds=self._cf_cache_ttl)
            cf_retry = await self._try_curl_cffi(url, method, headers, timeout, cookies=solved.cookies)
            if cf_retry.ok:
                return cf_retry
            return solved
        return solved

    async def get(self, url: str, headers: Optional[dict] = None, timeout: int = 30) -> FetchResult:
        return await self.fetch(url, "GET", headers=headers, timeout=timeout)

    async def _try_curl_cffi(
        self,
        url: str,
        method: str,
        headers: Optional[dict],
        timeout: int,
        cookies: Optional[dict],
    ) -> FetchResult:
        try:
            from .curl_cffi_fetcher import CurlCffiFetcher
            sync_fetcher = CurlCffiFetcher()
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: sync_fetcher.fetch(url, method=method, headers=headers, timeout=timeout, cookies=cookies),
            )
        except Exception as exc:
            logger.warning("EscalatingFetcher: curl_cffi fallback failed for %s: %s", url, exc)
            return FetchResult(
                url=url,
                status_code=0,
                content=b"",
                headers={},
                final_url=url,
                error=f"curl_cffi fallback failed: {exc}",
            )


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower()
