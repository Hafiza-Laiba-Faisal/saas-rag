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
        self._html_cache = {}
        self._progress_cb = None

    def set_progress_callback(self, cb):
        self._progress_cb = cb

    def _update_progress(self, pct: int, msg: str):
        if self._progress_cb:
            self._progress_cb(pct, msg)
        logger.info("[%d%%] %s", pct, msg)

    async def _fetch_url(self, url: str, timeout: int = 20) -> FetchResult:
        if url not in self._html_cache:
            self._html_cache[url] = await self.fetcher.get(url, timeout=timeout)
        return self._html_cache[url]

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

        self._update_progress(2, "Fetching homepage...")
        try:
            fetch_result = await self._fetch_url(url)
            if not fetch_result.ok:
                result.error = f"Failed to fetch: HTTP {fetch_result.status_code}"
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            html = fetch_result.text
            tree = self.parser.parse(html)

            is_wp = self.wp_detector.detect(html, url)
            result.is_wordpress = is_wp

            self._update_progress(8, "Detecting languages...")
            langs = await self._detect_languages(url, html)
            result.languages = langs

            all_pages: list[dict] = []
            all_media: list[dict] = []

            if is_wp:
                result.strategy_used = "wordpress_rest_api"
                self._update_progress(10, "WordPress detected — fetching via REST API...")
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
            self._update_progress(15, "Discovering pages via recursive crawl...")
            discovered = await self._recursive_discover(url, max_depth, max_pages)
            discovered_urls = {p["url"] for p in all_pages}
            new_pages = [p for p in discovered if p["url"] not in discovered_urls]
            if new_pages:
                logger.info("Recursive crawl found %d additional pages", len(new_pages))
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

            content_files = await self._extract_pages_content(all_pages, out_dir, by_lang, primary_lang, domain)
            result.content_files = content_files

            if download_images:
                self._update_progress(65, "Discovering images...")
                all_images = await self._discover_all_images(all_pages, page_title_map)
                result.images = all_images
                imgs_by_lang: dict[str, list[dict]] = {}
                for img in all_images:
                    pu = img.get("page_url", "")
                    img_lang = _lang_from_url(pu, domain, default_lang=primary_lang)
                    imgs_by_lang.setdefault(img_lang, []).append(img)

                self._update_progress(70, f"Downloading {len(all_images)} images...")
                total_dl = 0
                for lang_code, lang_imgs in sorted(imgs_by_lang.items()):
                    lang_dir = out_dir / "images" / lang_code
                    lang_dir.mkdir(parents=True, exist_ok=True)
                    dl = await self._bulk_download(lang_imgs, lang_dir, f"images/{lang_code}")
                    total_dl += dl
                logger.info("Downloaded %d/%d images across %d languages", total_dl, len(all_images), len(imgs_by_lang))
                result.stats["images_downloaded"] = total_dl
                result.stats["images_discovered"] = len(all_images)

            if download_pdfs:
                self._update_progress(85, "Discovering documents...")
                wp_docs = [m for m in all_media if m.get("mime") in ("application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]
                html_docs = await self._discover_pdfs_from_pages(all_pages)
                existing_urls = {p["url"] for p in wp_docs}
                for p in html_docs:
                    if p["url"] not in existing_urls:
                        wp_docs.append(p)

                result.pdfs = wp_docs
                docs_dir = out_dir / "documents"
                docs_dir.mkdir(parents=True, exist_ok=True)
                self._update_progress(90, f"Downloading {len(wp_docs)} documents...")
                downloaded = await self._bulk_download(
                    wp_docs, docs_dir, "document", key="url"
                )
                result.stats["pdfs_downloaded"] = downloaded
                result.stats["pdfs_discovered"] = len(wp_docs)

            self._update_progress(95, "Saving results...")
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

        except Exception as e:
            result.error = str(e)
            logger.exception("AutoCrawl failed for %s", url)

        result.elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        self._update_progress(100, result.error or f"Crawl complete — {result.stats.get('pages_found', 0)} pages, {result.stats.get('images_downloaded', 0)} images")
        return result

    async def _detect_languages(self, url: str, html: str) -> list[str]:
        found = set()
        domain = urlparse(url).netloc.lower()
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
    ) -> list[dict]:
        from collections import deque

        domain = urlparse(url).netloc.lower()
        seen = {url}
        queue = deque([(url, 0)])
        discovered = []

        while queue and len(seen) < max_pages:
            page_url, depth = queue.popleft()
            if depth > max_depth:
                continue
            try:
                fr = await self._fetch_url(page_url, timeout=20)
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

    async def _extract_pages_content(
        self,
        pages: list[dict],
        out_dir: Path,
        by_lang: dict[str, list[dict]],
        primary_lang: str,
        domain: str,
    ) -> list[dict]:
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
                        "title": title,
                        "url": page_url,
                        "lang": lang,
                        "file": str(md_path.relative_to(out_dir)),
                    })
                    continue

                try:
                    fr = await self._fetch_url(page_url, timeout=20)
                    if not fr.ok:
                        continue

                    readability = ReadabilityExtractor(base_url=page_url)
                    extracted = readability.extract(fr.text)
                    markdown = extracted.get("markdown", "")
                    clean_text = extracted.get("clean_text", "")

                    if not markdown and not clean_text:
                        continue

                    content = f"# {title}\n\n"
                    content += f"Source: {page_url}\n\n"
                    content += "---\n\n"
                    content += markdown or clean_text

                    md_path.write_text(content, encoding="utf-8")

                    # Write page metadata JSON
                    meta_path = md_path.with_suffix(".metadata.json")
                    page_meta = {
                        "url": page_url,
                        "title": title,
                        "language": lang,
                        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "file_type": "text/markdown",
                        "text_length": len(clean_text or markdown),
                    }
                    meta_path.write_text(json.dumps(page_meta, indent=2, ensure_ascii=False), encoding="utf-8")

                    content_files.append({
                        "title": title,
                        "url": page_url,
                        "lang": lang,
                        "file": str(md_path.relative_to(out_dir)),
                        "text_length": len(clean_text or markdown),
                    })
                except Exception:
                    continue

        return content_files

    async def _discover_all_images(
        self, pages: list[dict], page_title_map: dict
    ) -> list[dict]:
        all_imgs = []
        seen_urls = set()

        for p in pages:
            page_url = p["url"]
            try:
                fr = await self._fetch_url(page_url, timeout=20)
                if not fr.ok:
                    continue
                tree = self.parser.parse(fr.text)
                self.asset_ext.base_url = page_url
                assets = self.asset_ext.extract(tree)
                page_title = page_title_map.get(page_url, p.get("title", "page"))

                for img in assets.get("images", []):
                    src = img.get("src", "")
                    if src and src not in seen_urls and not src.startswith("data:"):
                        seen_urls.add(src)
                        all_imgs.append({
                            "url": src,
                            "alt": img.get("alt", ""),
                            "page_url": page_url,
                            "page_title": page_title,
                        })
            except Exception:
                continue

        return all_imgs

    async def _discover_pdfs_from_pages(self, pages: list[dict]) -> list[dict]:
        docs = []
        seen = set()

        for p in pages:
            page_url = p["url"]
            try:
                fr = await self._fetch_url(page_url, timeout=20)
                if not fr.ok:
                    continue
                tree = self.parser.parse(fr.text)
                self.asset_ext.base_url = page_url
                assets = self.asset_ext.extract(tree)

                for doc in assets.get("documents", []):
                    doc_url = doc["url"]
                    if doc_url not in seen:
                        seen.add(doc_url)
                        docs.append({
                            "url": doc_url,
                            "title": doc.get("text") or p.get("title", "document"),
                            "page_url": page_url,
                            "extension": doc.get("extension", ".bin"),
                            "source": "content_sniff",
                        })
            except Exception:
                continue

        return docs

    async def _bulk_download(
        self, items: list[dict], dest_dir: Path, label: str, key: str = "url"
    ) -> int:
        import hashlib
        sem = asyncio.Semaphore(5)
        downloaded = 0

        async def _dl(item: dict) -> bool:
            nonlocal downloaded
            url = item[key]
            page = item.get("page_title", "") or item.get("title", "file")
            alt = item.get("alt", "") or item.get("title", "file")

            # Extract extension & unique filename elements
            ext = Path(url.split("?")[0]).suffix or ".bin"
            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:6]
            url_path = urlparse(url).path
            orig_stem = Path(url_path).stem
            orig_ext = Path(url_path).suffix or ext

            if not orig_stem:
                orig_stem = _sanitize(alt or page or "file", 30)
            else:
                orig_stem = _sanitize(orig_stem, 30)

            if not orig_ext.startswith("."):
                orig_ext = f".{orig_ext}" if orig_ext else ext
            if orig_ext == ".":
                orig_ext = ext

            safe_page = _sanitize(page or "page", 20)
            fname = f"{safe_page}_{orig_stem}_{url_hash}{orig_ext}"
            fpath = dest_dir / fname

            # Companion metadata path
            meta_path = fpath.parent / f"{fpath.name}.metadata.json"

            if fpath.exists():
                downloaded += 1
                return True

            async with sem:
                try:
                    fr = await self.fetcher.get(url, timeout=30)
                    if fr.ok and fr.content:
                        fpath.write_bytes(fr.content)
                        downloaded += 1

                        # Generate mime/file type category
                        clean_ext = orig_ext.lstrip('.').lower()
                        if label.startswith("images") or clean_ext in ["jpg", "jpeg", "png", "gif", "svg", "webp", "ico"]:
                            file_type = f"image/{clean_ext}"
                        elif clean_ext in ["pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "zip"]:
                            file_type = f"application/{clean_ext}"
                        else:
                            file_type = "application/octet-stream"

                        # Write companion metadata JSON
                        asset_meta = {
                            "url": url,
                            "page_url": item.get("page_url", ""),
                            "page_title": item.get("page_title", "") or item.get("title", ""),
                            "alt_text": item.get("alt", ""),
                            "title": item.get("title", ""),
                            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "file_type": file_type,
                            "file_size_bytes": len(fr.content)
                        }
                        meta_path.write_text(json.dumps(asset_meta, indent=2, ensure_ascii=False), encoding="utf-8")
                        return True
                except Exception:
                    return False
            return False

        tasks = [_dl(item) for item in items]
        await asyncio.gather(*tasks)
        return downloaded
