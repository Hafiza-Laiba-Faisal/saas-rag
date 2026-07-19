import time
import os
from abc import ABC, abstractmethod
import httpx
from typing import Optional

from .base import FetchResult
from .client import get_async_client
from config.settings import DEFAULT_USER_AGENT, REQUEST_TIMEOUT, MAX_DOWNLOAD_SIZE

class AsyncBaseFetcher(ABC):
    @abstractmethod
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        timeout: int = REQUEST_TIMEOUT,
        **kwargs,
    ) -> FetchResult:
        ...

    async def get(self, url: str, headers: Optional[dict] = None, timeout: int = REQUEST_TIMEOUT) -> FetchResult:
        return await self.fetch(url, "GET", headers=headers, timeout=timeout)

# Full browser-like headers to bypass bot detection
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "DNT": "1",
    "Cache-Control": "max-age=0",
}


class AsyncHttpxFetcher(AsyncBaseFetcher):
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT):
        self._ua = user_agent

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        timeout: int = REQUEST_TIMEOUT,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        **kwargs,
    ) -> FetchResult:
        # Build full browser-like header set
        merged_headers = {"User-Agent": self._ua, **_BROWSER_HEADERS}
        # Add conditional request headers for cache/304 support
        if etag:
            merged_headers["If-None-Match"] = etag
        if last_modified:
            merged_headers["If-Modified-Since"] = last_modified
        # Caller-supplied headers override defaults
        if headers:
            merged_headers.update(headers)

        client = get_async_client()
        start = time.monotonic()

        # Stream response to allow early abort on large Content-Length
        async with client.stream(method, url, headers=merged_headers, timeout=timeout, **kwargs) as response:
            status_code = response.status_code
            headers_dict = dict(response.headers)
            final_url = str(response.url)

            if status_code == 304:
                elapsed = (time.monotonic() - start) * 1000
                return FetchResult(
                    url=url,
                    status_code=304,
                    content=b"",
                    headers=headers_dict,
                    elapsed_ms=round(elapsed, 2),
                    final_url=final_url,
                    cookies={},
                    error=None if status_code < 400 else f'HTTP {status_code}',
                )

            # Check if we got a bot block (403/429) and have DeepCrawl configured
            api_key = os.environ.get("DEEPCRAWL_API_KEY") if status_code in {403, 429} else None
            if api_key:
                # Fallback to Deepcrawl API transparently
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[DeepCrawl] Attempting fallback for {url} (status={status_code})")
                try:
                    payload = {
                        "url": url,
                        "includeHtml": True,
                        "includeMarkdown": True,
                        "includeMetadata": True,
                        "includeLinks": True,
                    }
                    dc_headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    async with httpx.AsyncClient(timeout=timeout) as dc_client:
                        dc_resp = await dc_client.post(
                            "https://api.deepcrawl.dev/read",
                            headers=dc_headers,
                            json=payload,
                        )
                    logger.info(f"[DeepCrawl] API response: {dc_resp.status_code}")
                    if dc_resp.status_code == 200:
                        dc_data = dc_resp.json()
                        html_content = dc_data.get("html") or dc_data.get("cleanedHtml") or ""
                        logger.info(f"[DeepCrawl] SUCCESS! Got {len(html_content)} chars of HTML")
                        elapsed = (time.monotonic() - start) * 1000
                        return FetchResult(
                            url=url,
                            status_code=200,
                            content=html_content.encode("utf-8"),
                            headers={**headers_dict, "content-type": "text/html"},
                            elapsed_ms=round(elapsed, 2),
                            final_url=final_url,
                            cookies={},
                            error=None,
                        )
                    else:
                        logger.warning(f"[DeepCrawl] API failed with status {dc_resp.status_code}")
                except Exception as dc_err:
                    # Log the deepcrawl error and fall through to original 403/429 response
                    logger.error(f"[DeepCrawl] Exception: {dc_err}", exc_info=True)
                    pass

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOWNLOAD_SIZE:
                raise ValueError(
                    f"Content-Length {content_length} exceeds MAX_DOWNLOAD_SIZE {MAX_DOWNLOAD_SIZE}"
                )

            content = await response.aread()

            # Decompress if the server sent gzip/deflate/br (httpx.stream()
            # does NOT auto-decode, unlike httpx.Client.request()).
            ce = headers_dict.get("content-encoding", "").lower()
            if ce in ("gzip", "x-gzip"):
                import gzip
                try:
                    content = gzip.decompress(content)
                except Exception:
                    pass
            elif ce == "deflate":
                import zlib
                try:
                    content = zlib.decompress(content)
                except Exception:
                    pass
            elif ce == "br":
                try:
                    import brotli
                    content = brotli.decompress(content)
                except ImportError:
                    pass
                except Exception:
                    pass

        elapsed = (time.monotonic() - start) * 1000

        return FetchResult(
            url=url,
            status_code=status_code,
            content=content,
            headers=headers_dict,
            elapsed_ms=round(elapsed, 2),
            final_url=final_url,
            cookies={},
            error=None if status_code < 400 else f'HTTP {status_code}',
        )

    async def download_stream(
        self,
        url: str,
        dest_path,
        max_size_bytes: int = MAX_DOWNLOAD_SIZE,
    ) -> int:
        """Stream large files to disk, aborting early if size limit exceeded. Returns bytes written."""
        merged_headers = {"User-Agent": self._ua, **_BROWSER_HEADERS}
        client = get_async_client()
        async with client.stream("GET", url, headers=merged_headers) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_size_bytes:
                raise ValueError(f"Content-Length {content_length} exceeds limit {max_size_bytes}")

            written = 0
            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes(65536):
                    written += len(chunk)
                    if written > max_size_bytes:
                        raise ValueError(f"Download exceeded size limit {max_size_bytes} bytes")
                    f.write(chunk)
        return written
