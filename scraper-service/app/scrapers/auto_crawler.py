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
from core.content.readability_extractor import ReadabilityExtractor

logger = logging.getLogger(__name__)

_KNOWN_LANG_CODES = {"it", "fr", "de", "en", "es", "pt", "ru", "zh", "ja", "ko", "ar", "nl", "pl", "tr", "sv"}


def _lang_from_url(url: str, site_domain: str = "", default_lang: str = "default") -> str:
    path = url.replace(f"https://{site_domain}", "").replace(f"http://{site_domain}", "").lstrip("/")
    first_seg = path.split("/")[0] if path else ""
    if first_seg in _KNOWN_LANG_CODES:
        return first_seg
    return default_lang


def _sanitize(name: str, max_len: int = 40) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()[:max_len]


@dataclass
class AutoCrawlResult:
    url: str
    is_wordpress: bool = False
    strategy_used: str = ""
    pages: list[dict] = field(default_factory=list)
    pages_by_language: dict[str, list[dict]] = field(default_factory=dict)
    content_files: list[dict] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    pdfs: list[dict] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    output_dir: str = ""
    error: Optional[str] = None
    elapsed_ms: float = 0


class AutoCrawler:
    def __init__(self, output_base: str = "crawl_output"):
        self.fetcher = EscalatingFetcher()
        self.parser = BS4Parser()
        self.meta_ext = DefaultMetadataExtractor()
        self.links_ext = DefaultLinksExtractor()
        self.asset_ext = AssetExtractor()
        self.wp_detector = WordPressDetector()
        self.output_base = Path(output_base)
        self._progress_cb = None

    def set_progress_callback(self, cb):
        self._progress_cb = cb

    def _progress(self, pct: int, msg: str):
        logger.info("[%d%%] %s", pct, msg)
        if self._progress_cb:
            self._progress_cb(pct, msg)

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
            self._progress(2, "Fetching homepage...")
            fetch_result = await self.fetcher.get(url)
            if not fetch_result.ok:
                result.error = f"Failed to fetch: HTTP {fetch_result.status_code}"
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            html = fetch_result.text
            tree = self.parser.parse(html)

            is_wp = self.wp_detector.detect(html, url)
            result.is_wordpress = is_wp

            self._progress(8, "Detecting languages...")
            langs = await self._detect_languages(url, html)
            result.languages = langs

            all_pages: list[dict] = []
            all_media: list[dict] = []

            if is_wp:
                result.strategy_used = "wordpress_rest_api"
                self._progress(12, "WordPress detected — querying REST API...")
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

            domain = urlparse(url).netloc.lower()
            self._progress(15, "Discovering pages via recursive crawl...")
            discovered, crawl_results = await self._recursive_discover(url, max_depth, max_pages)
            discovered_urls = {p["url"] for p in all_pages}
            new_pages = [p for p in discovered if p["url"] not in discovered_urls]
            if new_pages:
                all_pages.extend(new_pages)
                result.strategy_used = "hybrid" if is_wp else "recursive"

            primary_lang = "default"
            html_tag = tree.find("html")
            if html_tag and html_tag.get("lang"):
                hl = html_tag["lang"].split("-")[0]
                if hl in _KNOWN_LANG_CODES:
                    primary_lang = hl
            if primary_lang == "default" and langs:
                primary_lang = langs[0]

            by_lang: dict[str, list[dict]] = {}
            for p in all_pages:
                lang = _lang_from_url(p["url"], domain, default_lang=primary_lang)
                by_lang.setdefault(lang, []).append(p)
            result.pages_by_language = dict(sorted(by_lang.items()))

            page_title_map = {}
            for p in all_pages:
                page_title_map[p["url"]] = p.get("title", "page")
            homepage_meta = self.meta_ext.extract(tree, url)
            homepage_title = homepage_meta.get("og_title") or homepage_meta.get("title", "Homepage")
            page_title_map[url] = homepage_title

            result.pages = all_pages

            self._progress(30, "Extracting page text content...")
            content_files = self._save_content_from_results(
                crawl_results, all_pages, out_dir, by_lang, primary_lang, domain
            )
            result.content_files = content_files

            if download_images:
                self._progress(50, "Discovering images from all pages...")
                all_images = self._collect_images_from_results(crawl_results, all_pages, page_title_map)
                result.images = all_images
                imgs_by_lang: dict[str, list[dict]] = {}
                for img in all_images:
                    pu = img.get("page_url", "")
                    img_lang = _lang_from_url(pu, domain, default_lang=primary_lang)
                    imgs_by_lang.setdefault(img_lang, []).append(img)

                total_dl = 0
                for lang_code, lang_imgs in sorted(imgs_by_lang.items()):
                    lang_dir = out_dir / "images" / lang_code
                    lang_dir.mkdir(parents=True, exist_ok=True)
                    self._progress(55, f"Downloading {len(lang_imgs)} images for '{lang_code}'...")
                    dl = await self._bulk_download(lang_imgs, lang_dir, f"images/{lang_code}")
                    total_dl += dl
                result.stats["images_downloaded"] = total_dl
                result.stats["images_discovered"] = len(all_images)

            if download_pdfs:
                self._progress(80, "Discovering and downloading PDFs...")
                wp_pdfs = [m for m in all_media if m.get("mime") == "application/pdf"]
                html_pdfs = self._collect_pdfs_from_results(crawl_results)
                existing_urls = {p["url"] for p in wp_pdfs}
                for p in html_pdfs:
                    if p["url"] not in existing_urls:
                        wp_pdfs.append(p)

                result.pdfs = wp_pdfs
                pdfs_dir = out_dir / "pdfs"
                pdfs_dir.mkdir(parents=True, exist_ok=True)
                downloaded = await self._bulk_download(wp_pdfs, pdfs_dir, "pdf", key="url")
                result.stats["pdfs_downloaded"] = downloaded
                result.stats["pdfs_discovered"] = len(wp_pdfs)

            self._progress(95, "Saving results...")
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
                "content_files": content_files,
                "media": all_media,
                "pdfs": result.pdfs,
                "stats": result.stats,
            }
            (out_dir / "index.json").write_text(
                json.dumps(meta, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )

            result.stats["pages_found"] = len(all_pages)
            result.stats["media_found"] = len(all_media)
            result.stats["languages"] = langs
            result.stats["content_files_saved"] = len(content_files)
            n = result.stats["pages_found"]
            self._progress(100, f"Crawl complete — {n} pages, {result.stats.get('images_downloaded', 0)} images, {result.stats.get('pdfs_downloaded', 0)} PDFs")

        except Exception as e:
            result.error = str(e)
            logger.exception("AutoCrawl failed for %s", url)

        result.elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return result

    async def _detect_languages(self, url: str, html: str) -> list[str]:
        found = set()
        tree = self.parser.parse(html)

        for a in tree.find_all("a", href=True):
            href = a["href"]
            for code in _KNOWN_LANG_CODES:
                if f"/{code}/" in href:
                    found.add(code)

        for link in tree.find_all("link", rel="alternate"):
            hl = link.get("hreflang", "")
            if hl and hl != "x-default":
                found.add(hl.split("-")[0])

        html_tag = tree.find("html")
        if html_tag and html_tag.get("lang"):
            hl = html_tag["lang"].split("-")[0]
            if hl in _KNOWN_LANG_CODES:
                found.add(hl)

        return sorted(found) if found else ["default"]

    async def _recursive_discover(
        self, url: str, max_depth: int, max_pages: int
    ) -> tuple[list[dict], list]:
        from core.crawler.recursive_crawler import RecursiveCrawler

        crawler = RecursiveCrawler(
            seed_url=url,
            max_depth=max_depth,
            max_pages=max_pages,
            respect_robots=False,
            timeout=25,
            workers=3,
        )
        results = await crawler.crawl()

        discovered = []
        for r in results:
            if r.error:
                continue
            discovered.append({
                "title": r.title or urlparse(r.url).path.strip("/") or r.url,
                "url": r.url,
                "depth": r.depth,
                "source": "recursive",
            })

        return discovered, results

    def _save_content_from_results(
        self,
        crawl_results: list,
        all_pages: list[dict],
        out_dir: Path,
        by_lang: dict[str, list[dict]],
        primary_lang: str,
        domain: str,
    ) -> list[dict]:
        result_map = {r.url: r for r in crawl_results if not r.error}
        content_files = []
        pages_dir = out_dir / "pages"

        for lang, lang_pages in by_lang.items():
            lang_dir = pages_dir / lang
            lang_dir.mkdir(parents=True, exist_ok=True)

            for p in lang_pages:
                page_url = p["url"]
                title = p.get("title", "untitled")
                safe_name = _sanitize(title)
                md_path = lang_dir / f"{safe_name}.md"

                if md_path.exists():
                    content_files.append({
                        "title": title, "url": page_url, "lang": lang,
                        "file": str(md_path.relative_to(out_dir)),
                    })
                    continue

                cr = result_map.get(page_url)
                if cr and cr.readability:
                    markdown = cr.readability.get("markdown", "")
                    clean_text = cr.readability.get("clean_text", "")
                    text = markdown or clean_text
                else:
                    continue

                if not text:
                    continue

                content = f"# {title}\n\nSource: {page_url}\n\n---\n\n{text}"
                md_path.write_text(content, encoding="utf-8")
                content_files.append({
                    "title": title, "url": page_url, "lang": lang,
                    "file": str(md_path.relative_to(out_dir)),
                    "text_length": len(text),
                })

        return content_files

    def _collect_images_from_results(
        self, crawl_results: list, all_pages: list[dict], page_title_map: dict
    ) -> list[dict]:
        seen_urls = set()
        all_imgs = []

        for cr in crawl_results:
            if cr.error or not cr.assets:
                continue
            page_title = page_title_map.get(cr.url, "")
            for img in cr.assets.get("images", []):
                src = img.get("src", "")
                if src and src not in seen_urls and not src.startswith("data:"):
                    seen_urls.add(src)
                    all_imgs.append({
                        "url": src, "alt": img.get("alt", ""),
                        "page_url": cr.url, "page_title": page_title,
                    })

        for p in all_pages:
            pu = p["url"]
            if pu not in {r.url for r in crawl_results}:
                seen_urls.discard(pu)

        return all_imgs

    def _collect_pdfs_from_results(self, crawl_results: list) -> list[dict]:
        pdfs = []
        seen = set()
        for cr in crawl_results:
            if cr.error or not cr.assets:
                continue
            for doc in cr.assets.get("documents", []):
                url = doc.get("url", "")
                if url and url.lower().endswith(".pdf") and url not in seen:
                    seen.add(url)
                    pdfs.append({
                        "url": url,
                        "title": doc.get("text", "") or cr.title or "document",
                        "page_url": cr.url,
                        "source": "content_sniff",
                    })
        return pdfs

    async def _bulk_download(
        self, items: list[dict], dest_dir: Path, label: str, key: str = "url"
    ) -> int:
        sem = asyncio.Semaphore(5)
        downloaded = 0

        async def _dl(item: dict) -> bool:
            nonlocal downloaded
            url = item[key]
            page = item.get("page_title", "") or item.get("title", "file")
            alt = item.get("alt", "") or item.get("title", "file")
            ext = Path(url.split("?")[0]).suffix or ".bin"
            safe_page = _sanitize(page, 30)
            safe_alt = _sanitize(alt, 30)
            fname = f"{safe_page}_{safe_alt}{ext}"
            fpath = dest_dir / fname
            if fpath.exists():
                downloaded += 1
                return True
            async with sem:
                try:
                    fr = await self.fetcher.get(url, timeout=30)
                    if fr.ok and fr.content:
                        fpath.write_bytes(fr.content)
                        downloaded += 1
                        return True
                except Exception:
                    return False
            return False

        tasks = [_dl(item) for item in items]
        await asyncio.gather(*tasks)
        return downloaded
