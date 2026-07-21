"""
Recursive web crawler with full pipeline integration.
Supports concurrent crawling, queue statistics, timing breakdown, and file output.
"""
from __future__ import annotations
import time
import asyncio
import hashlib
import uuid
import json
import logging
from typing import Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin


from core.fetcher.async_httpx_fetcher import AsyncHttpxFetcher
from core.fetcher.escalating_fetcher import EscalatingFetcher
from core.crawler.rate_limiter import AsyncDomainRateLimiter
from core.parser.bs4_parser import BS4Parser
from core.extractor.metadata_extractor import DefaultMetadataExtractor
from core.extractor.links_extractor import DefaultLinksExtractor
from core.extractor.pdf_extractor import PDFExtractor
from core.extractor.asset_extractor import AssetExtractor
from core.content.readability_extractor import ReadabilityExtractor
from core.content.detector import ContentDetector, ContentType
from core.crawler.sitemap_parser import SitemapParser
from .scheduler import URLScheduler

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    """Result of crawling a single page."""
    url: str
    status_code: int = 0
    content_type: ContentType = ContentType.UNKNOWN
    title: str = ""
    description: str = ""
    metadata: dict = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    depth: int = 0
    elapsed_ms: float = 0
    error: Optional[str] = None
    crawled_at: datetime = field(default_factory=datetime.utcnow)
    timing: dict = field(default_factory=dict)
    readability: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)


@dataclass
class CrawlStats:
    """Overall crawl statistics."""
    total_pages: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    html_pages: int = 0
    pdf_files: int = 0
    images: int = 0
    other_files: int = 0
    total_time_sec: float = 0
    pages_per_second: float = 0
    # Queue stats
    queued_urls: int = 0
    visited_urls: int = 0
    duplicates_skipped: int = 0
    external_skipped: int = 0
    robots_skipped: int = 0
    max_depth_reached: int = 0


class RecursiveCrawler:
    """
    Production-grade recursive web crawler.
    """

    def __init__(
        self,
        seed_url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        respect_robots: bool = True,
        timeout: int = 30,
        follow_external: bool = False,
        workers: int = 1,
        on_page: Optional[Callable[[CrawlResult], None]] = None,
        on_progress: Optional[Callable[[CrawlStats], None]] = None,
        output_dir: Optional[str] = None,
    ):
        self.seed_url = seed_url
        self.timeout = timeout
        self.workers = max(1, workers)
        self.on_page = on_page
        self.on_progress = on_progress

        # Auto-set allowed_domains to seed domain when follow_external=False
        if not follow_external and allowed_domains is None:
            seed_domain = urlparse(seed_url).netloc.lower()
            allowed_domains = [seed_domain]

        # Components
        self.scheduler = URLScheduler(
            max_depth=max_depth,
            max_pages=max_pages,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            respect_robots=respect_robots,
        )
        self.fetcher = EscalatingFetcher()
        self.rate_limiter = AsyncDomainRateLimiter()
        self.parser = BS4Parser()
        self.meta_extractor = DefaultMetadataExtractor()
        self.links_extractor = DefaultLinksExtractor()
        self.content_detector = ContentDetector()
        self.asset_extractor = AssetExtractor()

        # Results & deduplication state
        self.results: list[CrawlResult] = []
        self.stats = CrawlStats()
        self._lock = asyncio.Lock()
        self._seen_hashes: set[str] = set()
        self._start_time: float = 0

        # Output directory for saving crawled data
        self.output_dir = Path(output_dir) if output_dir else Path("crawl_output") / urlparse(seed_url).netloc.replace(".", "_")


    async def crawl(self) -> list[CrawlResult]:
        self._start_time = time.time()
        
        is_sitemap = self.seed_url.endswith(".xml") or self.seed_url.endswith(".xml.gz") or "sitemap" in self.seed_url.lower()
        
        sitemap_urls = []
        if is_sitemap:
            sitemap_parser = SitemapParser(timeout=self.timeout)
            sitemap_urls = sitemap_parser.parse(self.seed_url)
        elif self.scheduler.respect_robots:
            parsed_seed = urlparse(self.seed_url)
            base_url = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
            sitemaps = self.scheduler.robots.get_sitemaps(base_url)
            if sitemaps:
                sitemap_parser = SitemapParser(timeout=self.timeout)
                for sm in sitemaps:
                    sitemap_urls.extend(sitemap_parser.parse(sm))

        if sitemap_urls:
            for u in sitemap_urls:
                self.scheduler.add_seed(u)
            if not is_sitemap:
                self.scheduler.add_seed(self.seed_url)
        else:
            if not self.scheduler.add_seed(self.seed_url):
                return []
                
        active_tasks = set()
        
        while not self.scheduler.is_complete() or active_tasks:
            while len(active_tasks) < self.workers:
                next_item = self.scheduler.get_next_url()
                if not next_item:
                    break
                url, depth = next_item
                task = asyncio.create_task(self._crawl_page(url, depth))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
                
            if not active_tasks:
                break
                
            done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
            
            for task in done:
                try:
                    result = task.result()
                    async with self._lock:
                        self.results.append(result)
                        self._update_stats(result)
                    if self.on_page:
                        if asyncio.iscoroutinefunction(self.on_page):
                            await self.on_page(result)
                        else:
                            self.on_page(result)
                    if self.on_progress:
                        if asyncio.iscoroutinefunction(self.on_progress):
                            await self.on_progress(self.stats)
                        else:
                            self.on_progress(self.stats)
                except Exception as e:
                    logger.error(f"Worker exception: {e}")

        # Final stats
        self.stats.total_time_sec = time.time() - self._start_time
        if self.stats.total_time_sec > 0:
            self.stats.pages_per_second = self.stats.total_pages / self.stats.total_time_sec

        q_stats = self.scheduler.get_stats()
        self.stats.queued_urls = q_stats.get("total_seen", 0)
        self.stats.visited_urls = q_stats.get("completed", 0)
        self.stats.duplicates_skipped = q_stats.get("duplicates_skipped", 0)
        self.stats.external_skipped = q_stats.get("external_skipped", 0)
        self.stats.robots_skipped = q_stats.get("robots_skipped", 0)
        self.stats.max_depth_reached = q_stats.get("max_depth_reached", 0)

        # Save results to disk
        await self._save_results()

        return self.results
    async def _crawl_page(self, url: str, depth: int) -> CrawlResult:
        result = CrawlResult(url=url, depth=depth)
        timing = {}

        crawl_delay = 0.0
        if self.scheduler.respect_robots:
            delay = self.scheduler.robots.get_crawl_delay(url, self.scheduler.user_agent)
            if delay:
                crawl_delay = delay
                
        await self.rate_limiter.acquire(url, crawl_delay)

        try:
            t0 = time.time()
            fetch_result = await self.fetcher.get(url, timeout=self.timeout)
            timing["fetch_ms"] = round((time.time() - t0) * 1000, 2)
            
            self.rate_limiter.record_response(url, fetch_result.status_code, fetch_result.headers)

            result.status_code = fetch_result.status_code
            result.elapsed_ms = fetch_result.elapsed_ms

            if not fetch_result.ok:
                result.error = f"HTTP {fetch_result.status_code}"
                self.scheduler.mark_failed(url, result.error)
                result.timing = timing
                return result

            result.content_type = self.content_detector.detect(
                url,
                fetch_result.headers
            )

            content_bytes = fetch_result.content or b""
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            async with self._lock:
                if content_hash in self._seen_hashes:
                    self.scheduler.queue.skip_duplicate()
                    self.scheduler.mark_completed(url)
                    result.error = "Duplicate content skipped"
                    result.timing = timing
                    return result
                self._seen_hashes.add(content_hash)

            if result.content_type == ContentType.PDF:
                downloads_dir = Path("downloads")
                downloads_dir.mkdir(exist_ok=True)
                pdf_filename = f"{uuid.uuid4()}.pdf"
                pdf_path = downloads_dir / pdf_filename
                pdf_path.write_bytes(content_bytes)

                pdf_extractor = PDFExtractor(use_ocr=True)
                try:
                    pdf_data = await asyncio.to_thread(pdf_extractor.extract_text, pdf_path)
                except Exception as e:
                    pdf_data = {"text": "", "pages": 0, "method": "direct", "metadata": {}, "error": str(e)}

                result.title = pdf_data.get("metadata", {}).get("title") or pdf_filename
                result.description = pdf_data.get("metadata", {}).get("subject", "")
                result.metadata = {
                    "pdf_path": str(pdf_path),
                    "pages": pdf_data.get("pages", 0),
                    "method": pdf_data.get("method", "direct"),
                    "pdf_metadata": pdf_data.get("metadata", {}),
                    "text": pdf_data.get("text", "")
                }

            elif self.content_detector.should_parse_html(result.content_type):
                html = fetch_result.text

                t1 = time.time()
                tree = self.parser.parse(html)
                timing["parse_ms"] = round((time.time() - t1) * 1000, 2)

                t2 = time.time()
                metadata = self.meta_extractor.extract(tree, url)
                result.title = metadata.get("og_title") or metadata.get("title", "")
                result.description = metadata.get("og_description") or metadata.get("description", "")
                result.metadata = metadata

                links_data = self.links_extractor.extract(tree, url)
                discovered_urls = [link["url"] for link in links_data["links"]]
                result.links = discovered_urls
                timing["extract_ms"] = round((time.time() - t2) * 1000, 2)

                readability_extractor = ReadabilityExtractor(base_url=url)
                result.readability = readability_extractor.extract(html)

                self.asset_extractor.base_url = url
                result.assets = self.asset_extractor.extract(tree)

                self.scheduler.add_discovered_urls(
                    discovered_urls,
                    parent_url=url,
                    current_depth=depth
                )

            self.scheduler.mark_completed(url)

        except Exception as e:
            result.error = str(e)
            self.scheduler.mark_failed(url, result.error)

        result.timing = timing
        return result
    def _update_stats(self, result: CrawlResult):
        """Update crawl statistics."""
        self.stats.total_pages += 1

        if result.error:
            if "Duplicate content skipped" in result.error:
                self.stats.skipped += 1
            else:
                self.stats.failed += 1
        else:
            self.stats.successful += 1

        # Content type stats
        if result.content_type == ContentType.HTML:
            self.stats.html_pages += 1
        elif result.content_type == ContentType.PDF:
            self.stats.pdf_files += 1
        elif result.content_type == ContentType.IMAGE:
            self.stats.images += 1
        else:
            self.stats.other_files += 1

    async def _save_results(self):
        """Save crawl results to disk in crawl_output directory."""
        try:
            # Create output directory
            self.output_dir.mkdir(parents=True, exist_ok=True)
            pages_dir = self.output_dir / "pages"
            pages_dir.mkdir(exist_ok=True)

            # Prepare data structures
            pages_by_language = {}
            pages_flat = []
            content_files = []
            media = []

            # Process each crawled page
            for result in self.results:
                if result.error:
                    continue

                # Add to flat list
                page_data = {
                    "title": result.title or "Untitled",
                    "url": result.url,
                    "depth": result.depth,
                    "source": "recursive",
                    "status": result.status_code,
                }
                if result.description:
                    page_data["description"] = result.description
                pages_flat.append(page_data)

                # Detect language from URL
                domain = urlparse(self.seed_url).netloc.lower()
                path = result.url.replace(f"https://{domain}", "").replace(f"http://{domain}", "").lstrip("/")
                first_seg = path.split("/")[0] if path else "default"
                known_langs = {"it", "fr", "de", "en", "es", "pt", "ru", "zh", "ja", "ko", "ar", "nl", "pl", "tr", "sv"}
                lang = first_seg if first_seg in known_langs else "default"

                # Add to language-specific list
                if lang not in pages_by_language:
                    pages_by_language[lang] = []
                pages_by_language[lang].append({
                    "title": result.title or "Untitled",
                    "url": result.url,
                    "source": "recursive",
                    "type": "page"
                })

                # Save page content as markdown
                if result.readability and (result.readability.get("markdown") or result.readability.get("clean_text")):
                    lang_dir = pages_dir / lang
                    lang_dir.mkdir(exist_ok=True)

                    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in (result.title or "untitled")).strip()[:40]
                    md_path = lang_dir / f"{safe_title}.md"

                    content = f"# {result.title or 'Untitled'}\n\n"
                    content += f"Source: {result.url}\n\n"
                    content += "---\n\n"
                    content += result.readability.get("markdown", "") or result.readability.get("clean_text", "")

                    md_path.write_text(content, encoding="utf-8")

                    content_files.append({
                        "title": result.title or "Untitled",
                        "url": result.url,
                        "lang": lang,
                        "file": f"pages/{lang}/{safe_title}.md",
                        "text_length": len(result.readability.get("clean_text", "") or result.readability.get("markdown", ""))
                    })

                # Collect media/assets
                if result.assets:
                    for img in result.assets.get("images", []):
                        media.append({
                            "url": img.get("src", ""),
                            "title": img.get("alt", "") or result.title,
                            "mime": "image/*",
                            "alt": img.get("alt", "")
                        })

            # Build index.json
            index_data = {
                "site": self.seed_url,
                "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "strategy": "recursive",
                "pages_by_language": dict(sorted(pages_by_language.items())),
                "pages_flat": pages_flat,
                "content_files": content_files,
                "media": media[:100],  # Limit media list
                "stats": {
                    "total_pages": self.stats.total_pages,
                    "successful": self.stats.successful,
                    "failed": self.stats.failed,
                    "html_pages": self.stats.html_pages,
                    "pdf_files": self.stats.pdf_files,
                    "images": self.stats.images,
                    "total_time_sec": round(self.stats.total_time_sec, 2),
                    "pages_per_second": round(self.stats.pages_per_second, 2),
                }
            }

            # Write index.json
            index_path = self.output_dir / "index.json"
            index_path.write_text(
                json.dumps(index_data, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8"
            )

            logging.info(f"Recursive crawl results saved to: {self.output_dir}")
            logging.info(f"Total pages saved: {len(content_files)}")

        except Exception as e:
            logging.error(f"Failed to save crawl results: {e}")

    def get_stats(self) -> CrawlStats:
        """Get current crawl statistics."""
        return self.stats

