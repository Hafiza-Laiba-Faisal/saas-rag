"""
AutoCrawler — fully automatic site scrape pipeline.

Strategy selection (per site):
  1. Detect WordPress → WP REST API (fast, structured)
  2. Detect language variants from homepage links
  3. Recursive crawl for undiscovered pages
  4. Download all images + PDFs with page-based naming
  5. Generate metadata index

Usage:
    from scrapers.auto_crawler import AutoCrawler
    crawler = AutoCrawler()
    result = await crawler.crawl("https://example.com")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from core.fetcher.escalating_fetcher import EscalatingFetcher
from core.parser.bs4_parser import BS4Parser
from core.detectors.wordpress_detector import WordPressDetector
from core.extractor.metadata_extractor import DefaultMetadataExtractor
from core.extractor.links_extractor import DefaultLinksExtractor
from core.extractor.asset_extractor import AssetExtractor

logger = logging.getLogger(__name__)


_KNOWN_LANG_CODES = {"it", "fr", "de", "en", "es", "pt", "ru", "zh", "ja", "ko", "ar", "nl", "pl", "tr", "sv"}


def _lang_from_url(url: str, site_domain: str = "", default_lang: str = "default") -> str:
    """Extract language code from URL path prefix."""
    path = url.replace(f"https://{site_domain}", "").replace(f"http://{site_domain}", "").lstrip("/")
    first_seg = path.split("/")[0] if path else ""
    if first_seg in _KNOWN_LANG_CODES:
        return first_seg
    return default_lang


@dataclass
class AutoCrawlResult:
    url: str
    is_wordpress: bool = False
    strategy_used: str = ""
    pages: list[dict] = field(default_factory=list)
    pages_by_language: dict[str, list[dict]] = field(default_factory=dict)
    media: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    pdfs: list[dict] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    output_dir: str = ""
    error: Optional[str] = None
    elapsed_ms: float = 0


class AutoCrawler:
    """Fully automatic site scraper. Detects platform, strategy, and languages."""

    def __init__(self, output_base: str = "crawl_output"):
        self.fetcher = EscalatingFetcher()
        self.parser = BS4Parser()
        self.meta_ext = DefaultMetadataExtractor()
        self.links_ext = DefaultLinksExtractor()
        self.asset_ext = AssetExtractor()
        self.wp_detector = WordPressDetector()
        self.output_base = Path(output_base)

    async def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        download_images: bool = True,
        download_pdfs: bool = True,
    ) -> AutoCrawlResult:
        start = time.monotonic()
        result = AutoCrawlResult(url=url)
        site_name = urlparse(url).netloc.replace(".", "_")
        out_dir = self.output_base / site_name
        out_dir.mkdir(parents=True, exist_ok=True)
        result.output_dir = str(out_dir)

        try:
            fetch_result = await self.fetcher.get(url)
            if not fetch_result.ok:
                result.error = f"Failed to fetch: HTTP {fetch_result.status_code}"
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            html = fetch_result.text
            tree = self.parser.parse(html)

            is_wp = self.wp_detector.detect(html, url)
            result.is_wordpress = is_wp

            langs = await self._detect_languages(url, html)
            result.languages = langs
            lang_suffix = f" (+{len(langs)-1} languages)" if langs else ""
            logger.info("Languages detected: %s", langs)

            all_pages: list[dict] = []
            all_media: list[dict] = []

            if is_wp:
                result.strategy_used = "wordpress_rest_api"
                logger.info("WordPress detected — using REST API")
                from .wordpress_scraper import WordPressScraper
                wp = WordPressScraper()
                wp_result = await wp.scrape(url, max_pages=10, include_pages=True, include_media=True)
                if wp_result.posts or wp_result.pages or wp_result.media:
                    for p in wp_result.pages:
                        all_pages.append({
                            "title": p.get("title", ""),
                            "url": p.get("link", ""),
                            "type": "page",
                            "source": "wp_api",
                        })
                    for p in wp_result.posts:
                        all_pages.append({
                            "title": p.get("title", ""),
                            "url": p.get("link", ""),
                            "type": "post",
                            "source": "wp_api",
                        })
                    all_media = wp_result.media

            result.pages = all_pages

            # Fill gaps with recursive crawl
            domain = urlparse(url).netloc.lower()
            discovered = await self._recursive_discover(url, max_depth, max_pages)
            discovered_urls = {p["url"] for p in all_pages}
            new_pages = [p for p in discovered if p["url"] not in discovered_urls]
            if new_pages:
                logger.info("Recursive crawl found %d additional pages", len(new_pages))
                all_pages.extend(new_pages)
                result.strategy_used = "hybrid" if is_wp else "recursive"

            # Determine primary language from HTML lang attribute
            primary_lang = "default"
            html_tag = tree.find("html")
            if html_tag and html_tag.get("lang"):
                hl = html_tag["lang"].split("-")[0]
                if hl in _KNOWN_LANG_CODES:
                    primary_lang = hl
            # Fall back to first detected language
            if primary_lang == "default" and langs:
                primary_lang = langs[0]

            # Group by language
            by_lang: dict[str, list[dict]] = {}
            for p in all_pages:
                lang = _lang_from_url(p["url"], domain, default_lang=primary_lang)
                by_lang.setdefault(lang, []).append(p)
            result.pages_by_language = dict(sorted(by_lang.items()))

            # Build page URL -> title + lang map for image naming
            page_title_map = {}
            for p in all_pages:
                page_title_map[p["url"]] = p.get("title", "page")
            homepage_title = (
                self.meta_ext.extract(tree, url).get("og_title")
                or self.meta_ext.extract(tree, url).get("title", "Homepage")
            )
            page_title_map[url] = homepage_title

            result.pages = all_pages

            # Discover + download images (language-separated)
            if download_images:
                all_images = await self._discover_all_images(all_pages, page_title_map)
                result.images = all_images
                # Group downloaded images by the language of their source page
                imgs_by_lang: dict[str, list[dict]] = {}
                for img in all_images:
                    pu = img.get("page_url", "")
                    img_lang = _lang_from_url(pu, domain, default_lang=primary_lang)
                    imgs_by_lang.setdefault(img_lang, []).append(img)

                total_dl = 0
                for lang_code, lang_imgs in sorted(imgs_by_lang.items()):
                    lang_dir = out_dir / "images" / lang_code
                    lang_dir.mkdir(parents=True, exist_ok=True)
                    dl = await self._bulk_download(lang_imgs, lang_dir, f"images/{lang_code}")
                    total_dl += dl
                logger.info("Downloaded %d/%d images across %d languages", total_dl, len(all_images), len(imgs_by_lang))
                result.stats["images_downloaded"] = total_dl
                result.stats["images_discovered"] = len(all_images)

            # Download PDFs (language-separated)
            if download_pdfs and all_media:
                pdf_items = [m for m in all_media if m.get("mime") == "application/pdf"]
                result.pdfs = pdf_items
                pdfs_dir = out_dir / "pdfs"
                pdfs_dir.mkdir(parents=True, exist_ok=True)
                downloaded = await self._bulk_download(
                    pdf_items, pdfs_dir, "pdf", key="url"
                )
                result.stats["pdfs_downloaded"] = downloaded

            # Save metadata — language-grouped index
            meta = {
                "site": url,
                "is_wordpress": is_wp,
                "strategy": result.strategy_used,
                "languages_found": langs,
                "languages_in_pages": list(by_lang.keys()),
                "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "pages_by_language": {
                    lang: [
                        {"title": p["title"], "url": p["url"], "source": p.get("source", ""), "type": p.get("type", "page")}
                        for p in pages
                    ]
                    for lang, pages in sorted(by_lang.items())
                },
                "pages_flat": result.pages,
                "media": all_media,
                "stats": result.stats,
            }
            (out_dir / "index.json").write_text(
                json.dumps(meta, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )

            result.stats["pages_found"] = len(all_pages)
            result.stats["media_found"] = len(all_media)
            result.stats["languages"] = langs

        except Exception as e:
            result.error = str(e)
            logger.exception("AutoCrawl failed for %s", url)

        result.elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return result

    async def _detect_languages(self, url: str, html: str) -> list[str]:
        """Detect language variants from homepage links or hreflang tags."""
        found = set()
        domain = urlparse(url).netloc.lower()
        tree = self.parser.parse(html)

        # 1. Check href links for language prefixes
        for a in tree.find_all("a", href=True):
            href = a["href"]
            for code in _KNOWN_LANG_CODES:
                if f"/{code}/" in href:
                    found.add(code)

        # 2. Check hreflang <link> tags (most reliable)
        for link in tree.find_all("link", rel="alternate"):
            hl = link.get("hreflang", "")
            if hl and hl != "x-default":
                found.add(hl.split("-")[0])

        # 3. Check html lang attribute
        html_tag = tree.find("html")
        if html_tag and html_tag.get("lang"):
            hl = html_tag["lang"].split("-")[0]
            if hl in _KNOWN_LANG_CODES:
                found.add(hl)

        return sorted(found) if found else ["default"]

    async def _recursive_discover(
        self, url: str, max_depth: int, max_pages: int
    ) -> list[dict]:
        """Simple BFS crawl to discover pages."""
        from collections import deque

        domain = urlparse(url).netloc.lower()
        seen = {url}
        queue = deque([(url, 0)])
        discovered = []

        base_result = await self.fetcher.get(url, timeout=30)

        while queue and len(seen) < max_pages:
            page_url, depth = queue.popleft()
            if depth > max_depth:
                continue
            try:
                fr = await self.fetcher.get(page_url, timeout=20)
                if not fr.ok:
                    continue
                tree = self.parser.parse(fr.text)
                meta = self.meta_ext.extract(tree, page_url)
                title = meta.get("og_title") or meta.get("title", "") or page_url
                links = self.links_ext.extract(tree, page_url)

                discovered.append({
                    "title": title,
                    "url": page_url,
                    "depth": depth,
                    "source": "recursive",
                })

                if depth < max_depth:
                    for lnk in links["links"]:
                        lu = lnk["url"]
                        if domain in lu and lu not in seen:
                            if not any(
                                skip in lu.lower()
                                for skip in [".pdf", ".jpg", ".png", ".svg", "#"]
                            ):
                                if lu.startswith(f"https://{domain}") or lu.startswith(f"http://{domain}"):
                                    seen.add(lu)
                                    queue.append((lu, depth + 1))
            except Exception:
                continue

        return discovered

    async def _discover_all_images(
        self, pages: list[dict], page_title_map: dict
    ) -> list[dict]:
        """Visit each page URL and collect all images with page context."""
        all_imgs = []
        seen_urls = set()

        for p in pages:
            url = p["url"]
            try:
                fr = await self.fetcher.get(url, timeout=20)
                if not fr.ok:
                    continue
                tree = self.parser.parse(fr.text)
                self.asset_ext.base_url = url
                assets = self.asset_ext.extract(tree)
                page_title = page_title_map.get(url, p.get("title", "page"))

                for img in assets.get("images", []):
                    src = img.get("src", "")
                    if src and src not in seen_urls and not src.startswith("data:"):
                        seen_urls.add(src)
                        all_imgs.append({
                            "url": src,
                            "alt": img.get("alt", ""),
                            "page_url": url,
                            "page_title": page_title,
                        })
            except Exception:
                continue

        return all_imgs

    async def _bulk_download(
        self, items: list[dict], dest_dir: Path, label: str, key: str = "url"
    ) -> int:
        """Download files concurrently with semaphore."""
        import httpx

        sem = asyncio.Semaphore(5)
        downloaded = 0

        async def _dl(item: dict) -> bool:
            nonlocal downloaded
            url = item[key]
            page = item.get("page_title", "page")
            alt = item.get("alt", "") or item.get("title", "file")
            ext = Path(url.split("?")[0]).suffix or ".bin"
            safe_page = "".join(c if c.isalnum() else "_" for c in page)[:30]
            safe_alt = "".join(c if c.isalnum() else "_" for c in alt)[:30]
            fname = f"{safe_page}_{safe_alt}{ext}"
            fpath = dest_dir / fname
            if fpath.exists():
                downloaded += 1
                return True
            async with sem:
                try:
                    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                        resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code == 200:
                        fpath.write_bytes(resp.content)
                        downloaded += 1
                        return True
                except Exception:
                    return False
            return False

        tasks = [_dl(item) for item in items]
        await asyncio.gather(*tasks)
        return downloaded
