"""HTTP Fetcher for web scraping"""
from __future__ import annotations

import asyncio
import httpx
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from rbs_rag.scraper.config import ScraperConfig, get_config
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class FetchResult:
    """Result of a fetch operation."""
    def __init__(
        self,
        url: str,
        status_code: int,
        content: bytes,
        content_type: str,
        headers: dict,
        error: Optional[str] = None,
    ):
        self.url = url
        self.status_code = status_code
        self.content = content
        self.content_type = content_type
        self.headers = headers
        self.error = error

    @property
    def is_success(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def save_to_file(self, file_path: Path) -> Path:
        """Save content to file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(self.content)
        return file_path


class HTTPFetcher:
    """Async HTTP fetcher with connection pooling and rate limiting."""

    def __init__(self, config: ScraperConfig = None):
        self.config = config or get_config()
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Initialize the HTTP client."""
        if self._client is None:
            limits = httpx.Limits(
                max_connections=self.config.max_concurrent_requests,
                max_keepalive_connections=self.config.max_concurrent_requests,
            )
            timeout = httpx.Timeout(self.config.request_timeout)
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=self.config.follow_redirects,
                verify=self.config.verify_ssl,
                headers={"User-Agent": self.config.user_agent},
            )
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        return self

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a single URL."""
        if not self._client:
            await self.start()

        async with self._semaphore:
            try:
                response = await self._client.get(url)
                await asyncio.sleep(self.config.delay_between_requests)
                
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    content=response.content,
                    content_type=response.headers.get("content-type", ""),
                    headers=dict(response.headers),
                )
            except httpx.TimeoutException:
                return FetchResult(url=url, status_code=0, content=b"", content_type="", headers={}, error="Timeout")
            except httpx.TooManyRedirects:
                return FetchResult(url=url, status_code=0, content=b"", content_type="", headers={}, error="Too many redirects")
            except Exception as e:
                logger.error("Fetch failed for %s: %s", url, e)
                return FetchResult(url=url, status_code=0, content=b"", content_type="", headers={}, error=str(e))

    async def fetch_multiple(self, urls: list[str]) -> list[FetchResult]:
        """Fetch multiple URLs concurrently."""
        tasks = [self.fetch(url) for url in urls]
        return await asyncio.gather(*tasks)

    def is_valid_url(self, url: str) -> bool:
        """Check if URL is valid."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    def normalize_url(self, base_url: str, href: str) -> str:
        """Normalize a relative URL against a base URL."""
        return urljoin(base_url, href)

    def is_same_domain(self, url1: str, url2: str) -> bool:
        """Check if two URLs are on the same domain."""
        return urlparse(url1).netloc == urlparse(url2).netloc