"""
Default fetcher implementation using httpx.
Future: swap with aiohttp or requests without changing any caller.
"""

from __future__ import annotations
import time
import httpx
from .base import BaseFetcher, FetchResult
from config.settings import DEFAULT_USER_AGENT, REQUEST_TIMEOUT


class HttpxFetcher(BaseFetcher):
    """Synchronous httpx fetcher with redirect following and configurable headers."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT):
        self._ua = user_agent

    def fetch(
        self,
        url:     str,
        method:  str = "GET",
        headers: dict | None = None,
        timeout: int = REQUEST_TIMEOUT,
        **kwargs,
    ) -> FetchResult:
        merged_headers = {"User-Agent": self._ua}
        if headers:
            merged_headers.update(headers)

        start = time.monotonic()
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.request(method, url, headers=merged_headers, **kwargs)
        elapsed = (time.monotonic() - start) * 1000

        return FetchResult(
            url=url,
            status_code=resp.status_code,
            content=resp.content,
            headers=dict(resp.headers),
            elapsed_ms=round(elapsed, 2),
            final_url=str(resp.url),
        )
