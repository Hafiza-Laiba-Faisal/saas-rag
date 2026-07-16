"""Main scraper engine for web scraping"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlencode, parse_qs

from bs4 import BeautifulSoup

from rbs_rag.scraper.config import ScraperConfig, get_config
from rbs_rag.scraper.fetcher.http_fetcher import HTTPFetcher, FetchResult, HAS_CURL_CFFI
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

    async def _deepcrawl_fetch(self, url: str) -> dict | None:
        """Try DeepCrawl API as fallback for blocked sites. Returns dict with markdown/html."""
        api_key = os.environ.get("DEEPCRAWL_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.deepcrawl.dev/read",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"url": url, "includeHtml": True, "includeMarkdown": True},
                )
                if resp.status_code != 200:
                    return None
                return resp.json()
        except Exception:
            return None

    async def scrape(self, url: str) -> ScrapeResult:
        """Scrape a single URL."""
        t0 = time.time()

        if not self._initialized:
            await self.start()

        if not self.fetcher.is_valid_url(url):
            return ScrapeResult(url=url, error=f"Invalid URL: {url}")

        fetch_result = await self.fetcher.fetch(url)
        ms = (time.time() - t0) * 1000

        # Try normal scrape
        if fetch_result.is_success and fetch_result.status_code not in {403, 429, 503}:
            html_content = fetch_result.text
            parsed = self.parser.parse(html_content, base_url=url)
            content = extract_readable_content(html_content, base_url=url)
            markdown = self._to_markdown(content, url)

            # Quality gate: reject content with too many non-printable / replacement chars
            if not self._is_clean_text(content):
                logger.warning("Content quality check failed for %s, trying fallback", url)

            # If content is meaningful, return it
            if len(content.strip()) > 200 and self._is_clean_text(content):
                return ScrapeResult(
                    url=url, title=parsed.title, content=content, markdown=markdown,
                    metadata=parsed.metadata, links=parsed.links, images=parsed.images,
                    status_code=fetch_result.status_code, processing_time_ms=ms,
                )

        # Fallback to DeepCrawl for blocked/empty sites
        dc_data = await self._deepcrawl_fetch(url)
        if dc_data:
            md = dc_data.get("markdown") or ""
            title = (dc_data.get("metadata") or {}).get("title", "") or ""
            markdown = self._to_markdown(md, url)
            return ScrapeResult(
                url=url, title=title, content=md, markdown=markdown,
                metadata=dc_data.get("metadata") or {},
                links=[], images=[], status_code=200,
                processing_time_ms=(time.time() - t0) * 1000,
            )

        msg = fetch_result.error or f"HTTP {fetch_result.status_code}"
        if fetch_result.status_code == 200 and not HAS_CURL_CFFI and self.fetcher._is_cloudflare_challenge(fetch_result.content):
            msg = "Site is behind Cloudflare — install curl_cffi (pip install curl_cffi)"
        return ScrapeResult(
            url=url,
            error=msg,
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

    async def _parse_sitemap(self, base_url: str) -> set[str]:
        """Try to parse sitemap.xml to discover all pages on a site. Uses the fetcher for Cloudflare bypass."""
        parsed = urlparse(base_url)
        candidates = [
            urljoin(base_url, "/sitemap.xml"),
            urljoin(base_url, "/sitemap_index.xml"),
            urljoin(base_url, "/wp-sitemap.xml"),
            f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        ]

        discovered = set()
        for sitemap_url in candidates:
            try:
                result = await self.fetcher.fetch(sitemap_url)
                if not result.is_success:
                    continue
                text = result.text

                locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text, re.IGNORECASE)

                # Follow sub-sitemaps (sitemap index)
                sub_sitemaps = [l for l in locs if l.strip().endswith(".xml") or "/sitemap" in l.strip().lower()]
                for sub in sub_sitemaps:
                    sub_result = await self.fetcher.fetch(sub.strip())
                    if sub_result.is_success:
                        sub_locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sub_result.text, re.IGNORECASE)
                        for sl in sub_locs:
                            sl = sl.strip()
                            if urlparse(sl).scheme in ("http", "https") and not sl.endswith(".xml"):
                                discovered.add(sl)

                for loc in locs:
                    loc = loc.strip()
                    if loc.endswith(".xml") or "/sitemap" in loc.lower():
                        continue
                    if urlparse(loc).scheme in ("http", "https"):
                        discovered.add(loc)

                if discovered:
                    logger.info(f"Sitemap: {len(discovered)} URLs from {sitemap_url}")
                    return discovered
            except Exception:
                continue

        return discovered

    NON_HTML_EXT = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".pdf", ".doc", ".docx", ".mp4", ".mp3", ".zip", ".woff", ".woff2", ".ttf", ".eot"}
    SOCIAL_SHARE_PATTERNS = {"/sharer/", "/shareArticle", "/share.php", "pinterest.com/pin/", "twitter.com/intent/", "linkedin.com/share"}

    @staticmethod
    def _is_crawlable(url: str, base_domain: str = "") -> bool:
        """Check if a URL should be crawled (not a file, not a social share, valid scheme)."""
        if not url.startswith("http"):
            return False
        if base_domain and base_domain not in url:
            return False
        lower = url.lower()
        if any(lower.endswith(ext) for ext in ScraperEngine.NON_HTML_EXT):
            return False
        if any(p in lower for p in ScraperEngine.SOCIAL_SHARE_PATTERNS):
            return False
        return True

    async def _discover_language_variants(self, base_url: str, base_domain: str) -> set[str]:
        """Discover language variant URLs (EN/FR/DE/ES) from hreflang tags or page links."""
        result = await self.scrape(base_url)
        if not result.is_success:
            return set()

        lang_urls = set()
        # Try hreflang tags first
        soup = BeautifulSoup("", "html.parser")
        try:
            fetch_result = await self.fetcher.fetch(base_url)
            if fetch_result.is_success:
                soup = BeautifulSoup(fetch_result.text, "html.parser")
                for link in soup.find_all("link", rel="alternate", hreflang=True):
                    href = link.get("href", "").strip()
                    if href and base_domain in href:
                        lang_urls.add(self._normalize_url(href))
        except Exception:
            pass

        # Fallback: look for language links in the page (common pattern: /en/, /fr/, etc.)
        if not lang_urls:
            lang_codes = {"en", "fr", "de", "es"}
            for link in result.links:
                if base_domain not in link:
                    continue
                parsed = urlparse(link)
                segs = parsed.path.strip("/").split("/")
                if segs and segs[0] in lang_codes:
                    lang_urls.add(self._normalize_url(link))

        return lang_urls

    async def _discover_urls(self, start_url: str, max_pages: int = 100, max_depth: int = 5) -> list[str]:
        """Discover all crawlable URLs on a site. Sitemap first, BFS fallback."""
        base_domain = urlparse(start_url).netloc
        all_urls: set[str] = set()

        # Tier 1: Sitemap
        sitemap_urls = await self._parse_sitemap(start_url)
        if sitemap_urls:
            for u in sitemap_urls:
                if self._is_crawlable(u, base_domain):
                    all_urls.add(self._normalize_url(u))

        # If sitemap gave us enough, try to discover language variants too
        if all_urls:
            lang_urls = await self._discover_language_variants(start_url, base_domain)
            for u in lang_urls:
                if self._is_crawlable(u, base_domain):
                    all_urls.add(u)
            if len(all_urls) >= max_pages:
                return list(all_urls)[:max_pages]

        # Tier 2: BFS fallback (no sitemap, or sitemap had too few)
        visited: set[str] = set()
        to_visit = [self._normalize_url(start_url)]

        while to_visit and len(visited) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if self._is_crawlable(url, base_domain) or url == self._normalize_url(start_url):
                all_urls.add(url)

            if len(visited) >= max_pages or len(visited) > max_depth * 10:
                continue

            result = await self.scrape(url)
            if not result.is_success:
                continue

            for link in result.links:
                if not self._is_crawlable(link, base_domain):
                    continue
                normalized = self._normalize_url(link)
                if normalized not in visited and normalized not in all_urls:
                    to_visit.append(normalized)

        return list(all_urls)[:max_pages]

    async def scrape_all(self, urls: list[str], max_concurrent: int = 5, time_cap: float = 60.0) -> list[ScrapeResult]:
        """Scrape multiple URLs in parallel with a time cap."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _scrape_one(url: str) -> ScrapeResult:
            async with semaphore:
                return await self.scrape(url)

        results = await asyncio.wait_for(
            asyncio.gather(*[_scrape_one(u) for u in urls], return_exceptions=True),
            timeout=time_cap,
        )

        final = []
        for r in results:
            if isinstance(r, ScrapeResult):
                final.append(r)
            else:
                final.append(ScrapeResult(url="", error=str(r)))
        return final

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for dedup: strip fragments, sort query params, drop tracking params."""
        parsed = urlparse(url)
        scheme = parsed.scheme
        netloc = parsed.netloc
        path = parsed.path.rstrip("/") or "/"

        # Strip fragment
        query = parsed.query

        # Filter out tracking / booking-only query params
        if query:
            params = parse_qs(query, keep_blank_values=True)
            filtered = {
                k: v for k, v in params.items()
                if not any(k.lower().startswith(t) for t in ("info", "utm_", "fbclid", "gclid"))
            }
            if not filtered:
                query = ""
            else:
                query = urlencode(sorted(filtered.items()), doseq=True)

        # Remove .en / .fr / .de / .it / .es language suffix from path for dedup
        if "." in path.lstrip("/") and not path.startswith("/en/") and path != "/en":
            parts = path.rsplit(".", 1)
            if len(parts) == 2 and parts[1] in {"en", "fr", "es", "it", "de"}:
                path = parts[0]

        normalized = f"{scheme}://{netloc}{path}"
        if query:
            normalized += f"?{query}"
        return normalized

    async def crawl_domain(
        self,
        start_url: str,
        max_pages: int = 10,
        max_depth: int = 2,
        same_domain_only: bool = True,
        full_site: bool = False,
    ) -> list[ScrapeResult]:
        """Crawl a domain starting from a URL."""
        base_domain = urlparse(start_url).netloc

        if full_site:
            max_pages = min(max(max_pages, 200), 500)
            max_depth = min(max(max_depth, 10), 20)
            logger.info(f"Full site mode: max_pages={max_pages}, max_depth={max_depth}")

            urls = await self._discover_urls(start_url, max_pages=max_pages, max_depth=max_depth)
            logger.info(f"Discovered {len(urls)} URLs for full site scrape")

            if not urls:
                return [ScrapeResult(url=start_url, error="No URLs discovered")]

            time_cap = min(max_pages * 5, 120)
            return await self.scrape_all(urls, max_concurrent=5, time_cap=time_cap)

        # Non-full-site: original BFS
        visited = set()
        to_visit = [(self._normalize_url(start_url), 0)]
        results = []

        while to_visit and len(visited) < max_pages:
            url, depth = to_visit.pop(0)
            if url in visited or depth > max_depth:
                continue
            visited.add(url)
            result = await self.scrape(url)
            results.append(result)

            if result.is_success and depth < max_depth:
                for link in result.links:
                    if not self._is_crawlable(link, base_domain):
                        continue
                    normalized = self._normalize_url(link)
                    if normalized not in visited:
                        to_visit.append((normalized, depth + 1))

        return results

    @staticmethod
    def _is_clean_text(text: str) -> bool:
        """Check if extracted text has acceptable quality (low replacement char ratio)."""
        if not text.strip():
            return False
        total = len(text)
        replacement_count = text.count("\ufffd")
        if total > 100 and replacement_count / total > 0.03:
            return False
        printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
        if printable / total < 0.80:
            return False
        return True

    def _to_markdown(self, text: str, url: str) -> str:
        """Convert text to simple markdown format."""
        lines = [f"Source: {url}", "", "---", ""]
        lines.append(text)
        return "\n".join(lines)