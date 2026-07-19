"""
WordPress scraper — full pipeline:
  detect → REST API (posts + pages + media) → HTML fallback.

Integrates with the existing escalation fetcher (Cloudflare/403 bypass)
and returns a structured result compatible with the CrawlResult pattern.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.fetcher.escalating_fetcher import EscalatingFetcher
from core.parser.bs4_parser import BS4Parser
from core.detectors.wordpress_detector import WordPressDetector
from core.extractor.wordpress_extractor import WordPressExtractor
from core.extractor.metadata_extractor import DefaultMetadataExtractor
from core.extractor.links_extractor import DefaultLinksExtractor

logger = logging.getLogger(__name__)


@dataclass
class WordPressCrawlResult:
    url: str
    is_wordpress: bool = False
    detected_by: str = ""
    posts: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: float = 0


class WordPressScraper:
    """Scrape WordPress sites via REST API with HTML fallback."""

    def __init__(self):
        self.fetcher = EscalatingFetcher()
        self.detector = WordPressDetector()
        self.parser = BS4Parser()
        self.meta_extractor = DefaultMetadataExtractor()
        self.links_extractor = DefaultLinksExtractor()

    async def scrape(
        self,
        url: str,
        max_pages: int = 10,
        include_pages: bool = True,
        include_media: bool = True,
    ) -> WordPressCrawlResult:
        start = time.monotonic()
        result = WordPressCrawlResult(url=url)

        try:
            fetch_result = await self.fetcher.get(url)
            if not fetch_result.ok:
                result.error = f"Failed to fetch: HTTP {fetch_result.status_code}"
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            html = fetch_result.text

            is_wp = self.detector.detect(html, url)
            if not is_wp:
                result.error = "Not a WordPress site (no WP markers detected)"
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            result.is_wordpress = True
            result.detected_by = "html_markers"

            tree = self.parser.parse(html)
            meta = self.meta_extractor.extract(tree, url)
            links_data = self.links_extractor.extract(tree, url)

            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            extractor = WordPressExtractor(base_url=base_url)

            posts = await extractor.extract_posts_via_api(max_pages=max_pages)
            if posts:
                result.posts = posts
                result.detected_by = "rest_api_posts"
            else:
                result.posts = extractor.extract_posts_from_html(tree)

            if include_pages:
                result.pages = await extractor.extract_pages_via_api()

            if include_media:
                pdf_media = await extractor.extract_media_via_api(
                    mime_type="application/pdf"
                )
                image_media = await extractor.extract_media_via_api()
                all_media = {m["url"]: m for m in pdf_media + image_media}
                result.media = list(all_media.values())

            result.stats = {
                "posts_found": len(result.posts),
                "pages_found": len(result.pages),
                "media_found": len(result.media),
                "pdf_count": sum(
                    1 for m in result.media if m.get("mime") == "application/pdf"
                ),
                "links_on_homepage": links_data["count"],
                "title": meta.get("og_title") or meta.get("title", ""),
                "description": meta.get(
                    "og_description"
                ) or meta.get("description", ""),
            }

        except Exception as e:
            result.error = str(e)
            logger.exception("WordPress scrape failed for %s", url)

        result.elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return result
