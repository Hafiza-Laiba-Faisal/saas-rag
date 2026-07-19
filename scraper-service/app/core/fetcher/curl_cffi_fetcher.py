from __future__ import annotations

import time
from typing import Any, Optional

from curl_cffi import requests as cf_requests
from curl_cffi.requests.exceptions import RequestException

from .base import FetchResult


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

IMPERSONATE_PROFILE = "chrome124"


class CurlCffiFetcher:
    """Synchronous fetcher using curl_cffi for TLS fingerprint impersonation."""

    def __init__(self, impersonate: str = IMPERSONATE_PROFILE, default_timeout: int = 30):
        self.impersonate = impersonate
        self.default_timeout = default_timeout

    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        cookies: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> FetchResult:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        start = time.monotonic()
        try:
            resp = cf_requests.request(
                method=method,
                url=url,
                headers=merged_headers,
                cookies=cookies,
                impersonate=self.impersonate,
                timeout=timeout or self.default_timeout,
                allow_redirects=True,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            content_bytes = resp.content if isinstance(resp.content, bytes) else resp.content.encode("utf-8")
            return FetchResult(
                url=url,
                status_code=resp.status_code,
                content=content_bytes,
                headers=dict(resp.headers),
                elapsed_ms=elapsed_ms,
                final_url=str(resp.url),
                cookies={c.name: c.value for c in resp.cookies.jar} if hasattr(resp.cookies, 'jar') else {},
                error=None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
        except RequestException as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            error_msg = str(exc)
            return FetchResult(
                url=url,
                status_code=0,
                content=b"",
                headers={},
                elapsed_ms=elapsed_ms,
                final_url=url,
                error=error_msg,
            )

    def get(self, url: str, headers: Optional[dict[str, str]] = None, timeout: int = 30, cookies: Optional[dict[str, str]] = None) -> FetchResult:
        return self.fetch(url, "GET", headers=headers, timeout=timeout, cookies=cookies)
