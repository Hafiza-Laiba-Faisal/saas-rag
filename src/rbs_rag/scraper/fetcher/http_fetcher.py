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

try:
    from curl_cffi.requests import AsyncSession as CurlSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


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
    """Async HTTP fetcher with connection pooling and rate limiting.

    Fallback chain:
      1. httpx (fast, lightweight)
      2. curl_cffi (Cloudflare bypass via TLS fingerprinting)
      3. Playwright (full JS rendering, anti-bot bypass)
    """

    def __init__(self, config: ScraperConfig = None):
        self.config = config or get_config()
        self._client: Optional[httpx.AsyncClient] = None
        self._curl_session: Optional[CurlSession] = None
        self._playwright_fetcher = None
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
                headers={
                    "User-Agent": self.config.user_agent,
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
                },
            )
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
            if HAS_CURL_CFFI:
                self._curl_session = CurlSession()
        return self

    async def close(self):
        """Close the HTTP client."""
        if self._curl_session:
            await self._curl_session.close()
            self._curl_session = None
        if self._playwright_fetcher:
            await self._playwright_fetcher.close()
            self._playwright_fetcher = None
        if self._client:
            await self._client.aclose()
            self._client = None

    CLOUDFLARE_PATTERNS = [
        b"__cf_chl_", b"cf_chl_opt", b"challenge-form",
        b"cf-browser-verification", b"cdn-cgi/challenge-platform",
        b"/cdn-cgi/l/challenge", b"Cloudflare",
    ]

    @staticmethod
    def _is_cloudflare_challenge(content: bytes) -> bool:
        """Detect whether the response is a Cloudflare challenge page."""
        lower = content.lower()
        for pat in HTTPFetcher.CLOUDFLARE_PATTERNS:
            if pat.lower() in lower:
                return True
        return False

    async def _fetch_via_curl(self, url: str) -> FetchResult | None:
        if not HAS_CURL_CFFI or not self._curl_session:
            return None
        try:
            response = await self._curl_session.get(url, impersonate="chrome124")
            result = FetchResult(
                url=url,
                status_code=response.status_code,
                content=response.content,
                content_type=response.headers.get("content-type", ""),
                headers=dict(response.headers),
            )
            if result.is_success and self._is_cloudflare_challenge(response.content):
                logger.info("curl_cffi got Cloudflare challenge for %s, falling back", url)
                return None
            return result
        except Exception:
            return None

    async def _fetch_via_playwright(self, url: str) -> FetchResult | None:
        if not self._playwright_fetcher:
            try:
                from rbs_rag.scraper.fetcher.playwright_fetcher import PlaywrightFetcher
                self._playwright_fetcher = PlaywrightFetcher(self.config)
                await self._playwright_fetcher.start()
            except Exception as e:
                logger.warning("Playwright not available: %s", e)
                return None
        try:
            result = await asyncio.wait_for(
                self._playwright_fetcher.fetch(url), timeout=20
            )
            if result.is_success and len(result.content) > 500:
                return result
        except asyncio.TimeoutError:
            logger.warning("Playwright timeout for %s", url)
        except Exception as e:
            logger.warning("Playwright fetch failed for %s: %s", url, e)
        return None

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a single URL with 3-tier fallback."""
        if not self._client:
            await self.start()

        async with self._semaphore:
            # Tier 1: httpx
            try:
                response = await asyncio.wait_for(
                    self._client.get(url), timeout=self.config.request_timeout
                )
                await asyncio.sleep(self.config.delay_between_requests)

                if response.status_code not in (403, 429, 503, 0):
                    if not self._is_cloudflare_challenge(response.content):
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            content=response.content,
                            content_type=response.headers.get("content-type", ""),
                            headers=dict(response.headers),
                        )
                    logger.info("httpx got Cloudflare challenge for %s, trying fallback", url)

                logger.info("httpx got %d for %s, trying fallback", response.status_code, url)
            except Exception:
                pass

            # Tier 2: curl_cffi (TLS fingerprint bypass)
            if HAS_CURL_CFFI:
                curl_result = await self._fetch_via_curl(url)
                if curl_result and curl_result.is_success:
                    return curl_result

            # Tier 3: Playwright (full browser rendering) - only for HTML pages
            if not url.endswith((".pdf", ".jpg", ".png", ".gif", ".svg", ".ico", ".css", ".js")):
                pw_result = await self._fetch_via_playwright(url)
                if pw_result:
                    return pw_result

            # All fallbacks failed
            return FetchResult(url=url, status_code=0, content=b"", content_type="", headers={}, error="All fetchers failed")

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