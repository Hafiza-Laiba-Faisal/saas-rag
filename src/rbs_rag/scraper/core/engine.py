"""Main scraper engine for web scraping"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from rbs_rag.scraper.config import ScraperConfig, get_config
from rbs_rag.scraper.fetcher.http_fetcher import HTTPFetcher, FetchResult
from rbs_rag.scraper.parsers.html_parser import HTMLParser, ParsedContent
from rbs_rag.scraper.extractors.readability import extract_readable_content
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class ScrapeResult:
    """Result of a scrape operation."""
    def __init__(
        self,
        url: str,
        title: str = "",
        content: str = "",
        markdown: str = "",
        metadata: dict = None,
        links: list[str] = None,
        images: list[str] = None,
        error: Optional[str] = None,
        status_code: int = 200,
        processing_time_ms: float = 0.0,
    ):
        self.url = url
        self.title = title
        self.content = content
        self.markdown = markdown
        self.metadata = metadata or {}
        self.links = links or []
        self.images = images or []
        self.error = error
        self.status_code = status_code
        self.processing_time_ms = processing_time_ms

    @property
    def is_success(self) -> bool:
        return self.error is None and bool(self.content.strip())

    def to_text(self) -> str:
        """Convert to plain text format."""
        lines = []
        if self.title:
            lines.append(f"# {self.title}")
            lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "markdown": self.markdown,
            "links": self.links[:20],  # Limit links in output
            "images": self.images[:10],
            "error": self.error,
            "status_code": self.status_code,
            "processing_time_ms": self.processing_time_ms,
        }


class ScraperEngine:
    """Main web scraper engine."""

    def __init__(self, config: ScraperConfig = None):
        self.config = config or get_config()
        self.fetcher = HTTPFetcher(self.config)
        self.parser = HTMLParser()
        self._initialized = False

    async def start(self):
        """Initialize the scraper engine."""
        if not self._initialized:
            await self.fetcher.start()
            self._initialized = True
        return self

    async def close(self):
        """Close the scraper engine."""
        await self.fetcher.close()
        self._initialized = False

    async def scrape(self, url: str) -> ScrapeResult:
        """Scrape a single URL."""
        t0 = time.time()

        if not self._initialized:
            await self.start()

        if not self.fetcher.is_valid_url(url):
            return ScrapeResult(url=url, error=f"Invalid URL: {url}")

        fetch_result = await self.fetcher.fetch(url)
        ms = (time.time() - t0) * 1000

        if not fetch_result.is_success:
            return ScrapeResult(
                url=url,
                error=fetch_result.error or f"HTTP {fetch_result.status_code}",
                status_code=fetch_result.status_code,
                processing_time_ms=ms,
            )

        html_content = fetch_result.text
        parsed = self.parser.parse(html_content, base_url=url)

        content = extract_readable_content(html_content, base_url=url)

        # Generate simple markdown from content
        markdown = self._to_markdown(content, url)

        return ScrapeResult(
            url=url,
            title=parsed.title,
            content=content,
            markdown=markdown,
            metadata=parsed.metadata,
            links=parsed.links,
            images=parsed.images,
            status_code=fetch_result.status_code,
            processing_time_ms=ms,
        )

    async def scrape_multiple(self, urls: list[str]) -> list[ScrapeResult]:
        """Scrape multiple URLs."""
        tasks = [self.scrape(url) for url in urls]
        return await asyncio.gather(*tasks)

    async def scrape_and_save(self, url: str, output_dir: Path) -> tuple[ScrapeResult, Optional[Path]]:
        """Scrape a URL and save the content to a file."""
        result = await self.scrape(url)
        if not result.is_success:
            return result, None

        # Generate a safe filename
        domain = urlparse(url).netloc
        safe_name = f"{domain}_{int(time.time())}.md"
        file_path = output_dir / safe_name

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(result.to_text(), encoding="utf-8")

        return result, file_path

    async def crawl_domain(
        self,
        start_url: str,
        max_pages: int = 10,
        max_depth: int = 2,
        same_domain_only: bool = True,
    ) -> list[ScrapeResult]:
        """Crawl a domain starting from a URL."""
        visited = set()
        to_visit = [(start_url, 0)]
        results = []
        base_domain = urlparse(start_url).netloc

        while to_visit and len(visited) < max_pages:
            url, depth = to_visit.pop(0)

            if url in visited or depth > max_depth:
                continue

            visited.add(url)
            result = await self.scrape(url)
            results.append(result)

            if result.is_success and depth < max_depth:
                for link in result.links:
                    link_domain = urlparse(link).netloc
                    if same_domain_only and link_domain != base_domain:
                        continue
                    if link not in visited and urlparse(link).scheme in ("http", "https"):
                        to_visit.append((link, depth + 1))

        return results

    def _to_markdown(self, text: str, url: str) -> str:
        """Convert text to simple markdown format."""
        lines = [f"Source: {url}", "", "---", ""]
        lines.append(text)
        return "\n".join(lines)