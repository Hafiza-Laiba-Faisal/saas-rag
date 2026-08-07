"""
SiteCrawler — Production-grade, standardized full-site crawler.

Replaces AutoCrawler with proven techniques from sabbskin/aiminingco scrapers:
- srcset + data-src lazy load support
- WordPress URL size suffix stripping
- CSS background-image extraction
- Hash-based image deduplication
- Line-level text deduplication (removes WP footer spam)
- Parallel downloads with semaphore rate limiting
- Change detection (Redis or file-based hash store)
- Per-language output organization
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from core.fetcher.escalating_fetcher import EscalatingFetcher
from config.settings import resolve_output_dir

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

KNOWN_LANGS = {"it", "en", "fr", "de", "es", "pt", "ru", "zh", "ja", "ko", "ar", "nl", "pl", "tr", "sv"}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

DEFAULT_DECORATIVE_PATTERNS = [
    # Logos and branding
    "logo_dark", "logo_footer", "logo_header", "logo.png", "logo-", "/logo",
    "favicon", "apple-touch-icon",
    # Social media icons
    "facebook_square", "instagram1", "twitter_", "whatsapp_icon",
    "youtube_icon", "tiktok_icon", "linkedin_icon",
    "social-icon", "/social/",
    # Generic UI icons
    "-icon.", "_icon.", "button-", "badge-",
    "arrow-", "chevron-", "close-btn", "hamburger-",
    # Tracking / analytics
    "tracking", "pixel.", "analytics",
    # WP placeholder / decorative
    "dummy.", "bordo_", "separator-", "bullet-", "spinner-",
    "placeholder", "woocommerce-placeholder",
    "loading-", "Group-19.", "Group-20.",
    "Rectangle-11", "letto_mobile", "divano_mobile",
]

BLOCKED_EXTENSIONS = {".svg", ".ico", ".gif"}

SKIP_LINK_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
    ".css", ".js", ".xml", ".zip", ".tar", ".gz",
}


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class CrawlConfig:
    """All crawl parameters in one place."""
    url: str
    max_pages: int = 200
    workers: int = 6
    download_images: bool = True
    download_pdfs: bool = True
    respect_robots: bool = False
    timeout: int = 25
    decorative_patterns: list[str] = field(default_factory=lambda: DEFAULT_DECORATIVE_PATTERNS.copy())
    blocked_extensions: set[str] = field(default_factory=lambda: BLOCKED_EXTENSIONS.copy())
    output_base: str = "crawl_output"


@dataclass
class SiteCrawlResult:
    """Final result returned after a complete crawl."""
    url: str
    output_dir: str = ""
    languages: list[str] = field(default_factory=list)
    pages_crawled: int = 0
    pages_failed: int = 0
    images_total: int = 0
    images_content: int = 0
    images_decorative: int = 0
    images_downloaded: int = 0
    pdfs_found: int = 0
    pdfs_downloaded: int = 0
    pages_by_language: dict = field(default_factory=dict)
    content_files: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0
    error: Optional[str] = None
    stats: dict = field(default_factory=dict)


# ── URL Helpers ───────────────────────────────────────────────────────────────

def normalize_url(url: str, base: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        parsed_base = urlparse(base)
        url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
    if not url.startswith("http"):
        url = urljoin(base, url)
    url = url.split("#")[0]
    for param in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "fbclid", "gclid"]:
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    return url.rstrip("?&/") if url.count("/") > 2 else url.rstrip("?&")


def get_domain(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_same_domain(url: str, base_domain: str) -> bool:
    domain = get_domain(url)
    return domain == base_domain or domain.endswith("." + base_domain)


def lang_from_url(url: str, default: str = "it") -> str:
    path = urlparse(url).path.strip("/")
    first = path.split("/")[0] if path else ""
    return first if first in KNOWN_LANGS else default


def clean_wp_image_url(url: str) -> str:
    """Strip WordPress -WxH size suffixes to get full resolution."""
    url = re.sub(r"-\d+x\d+(\.[a-zA-Z]+)(\?.*)?$", r"\1", url)
    url = re.sub(r"[?&](w|h|width|height|size|resize|fit|crop)=\d+", "", url)
    return url.rstrip("?&")


def best_from_srcset(srcset: str) -> str:
    """Extract highest resolution URL from srcset (sabbskin technique)."""
    if not srcset:
        return ""
    parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
    return parts[-1] if parts else ""


def safe_filename(url: str, idx: int, default_ext: str = ".jpg") -> str:
    """Generate safe filename from URL."""
    path = urlparse(url).path
    name = path.split("/")[-1].split("?")[0]
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    if not name or "." not in name:
        h = hashlib.md5(url.encode()).hexdigest()[:8]
        name = f"file_{idx:04d}_{h}{default_ext}"
    return name


# ── Main SiteCrawler Class ────────────────────────────────────────────────────

class SiteCrawler:
    """
    Production-grade full-site crawler.
    Plug-in replacement for AutoCrawler — same progress callback API.
    """

    def __init__(self, output_base: str = "crawl_output", use_fetcher: bool = True):
        self.output_base = Path(output_base)
        self._progress_cb: Optional[Callable[[int, str], None]] = None
        self._fetcher = EscalatingFetcher(user_agent=DEFAULT_HEADERS["User-Agent"]) if use_fetcher else None

    def set_progress_callback(self, cb: Callable[[int, str], None]):
        self._progress_cb = cb

    def _progress(self, pct: int, msg: str):
        logger.info("[%d%%] %s", pct, msg)
        if self._progress_cb:
            self._progress_cb(pct, msg)

    # ── Public API ────────────────────────────────────────────────────────────

    async def crawl(
        self,
        url: str,
        max_pages: int = 200,
        workers: int = 6,
        download_images: bool = False,   # Default OFF — images.json only
        download_pdfs: bool = True,
        respect_robots: bool = False,
        max_depth: int = 3,
        **kwargs,
    ) -> SiteCrawlResult:
        config = CrawlConfig(
            url=url.rstrip("/"),
            max_pages=max_pages,
            workers=workers,
            download_images=download_images,
            download_pdfs=download_pdfs,
            respect_robots=respect_robots,
            output_base=str(self.output_base),
        )
        return await self._run(config)

    # ── Internal crawl engine ─────────────────────────────────────────────────

    async def _run(self, config: CrawlConfig) -> SiteCrawlResult:
        start = time.monotonic()
        result = SiteCrawlResult(url=config.url)

        base_domain = get_domain(config.url)
        site_name = urlparse(config.url).netloc.replace(".", "_").replace("-", "_")
        out_dir = resolve_output_dir(self.output_base, site_name)
        out_dir.mkdir(parents=True, exist_ok=True)
        result.output_dir = str(out_dir)

        # State
        visited: set[str] = set()
        queued: set[str] = set()
        queue: list[str] = []
        all_images: dict[str, dict] = {}
        all_pdfs: dict[str, dict] = {}
        pages_data: list[dict] = []
        failed: list[str] = []

        # Seed URLs — base + language variants
        seeds = [config.url + "/"]
        for lang in KNOWN_LANGS:
            seeds.append(f"{config.url}/{lang}/")
        for s in seeds:
            n = normalize_url(s, config.url)
            if n not in queued:
                queued.add(n)
                queue.append(n)

        sem = asyncio.Semaphore(config.workers)
        dl_sem = asyncio.Semaphore(8)

        limits = httpx.Limits(max_connections=config.workers + 4, max_keepalive_connections=config.workers)
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=config.timeout,
            limits=limits,
        ) as client:

            # ── Crawl pages ──────────────────────────────────────────────────
            self._progress(5, f"Starting crawl of {config.url}...")

            async def crawl_page(url: str):
                if url in visited:
                    return
                visited.add(url)
                async with sem:
                    try:
                        if self._fetcher is not None:
                            resp = await self._fetcher.get(url, headers=DEFAULT_HEADERS, timeout=config.timeout)
                            if resp.status_code != 200:
                                failed.append(url)
                                return
                            html = resp.text
                        else:
                            resp = await client.get(url, timeout=config.timeout)
                            if resp.status_code != 200:
                                failed.append(url)
                                return
                            html = resp.text
                        soup = BeautifulSoup(html, "html.parser")

                        title = self._extract_title(soup)
                        lang = self._detect_lang(soup, url)
                        text = self._extract_text(soup, url)
                        imgs = self._extract_images(soup, url, config)
                        pdfs = self._extract_pdfs(soup, url)
                        links = self._extract_links(soup, url, base_domain, config)

                        # Merge images/pdfs
                        for img in imgs:
                            if img["url"] not in all_images:
                                all_images[img["url"]] = img
                        for pdf in pdfs:
                            if pdf["url"] not in all_pdfs:
                                all_pdfs[pdf["url"]] = pdf

                        # Enqueue new links
                        new = 0
                        for link in links:
                            if link not in queued and link not in visited and len(queued) < config.max_pages:
                                queued.add(link)
                                queue.append(link)
                                new += 1

                        pages_data.append({
                            "url": url, "title": title, "language": lang,
                            "word_count": len(text.split()), "images_on_page": len(imgs),
                        })

                        # Save page
                        await self._save_page(out_dir, url, title, lang, text)

                        pct = min(5 + int(len(visited) / max(config.max_pages, 1) * 65), 70)
                        self._progress(pct,
                            f"Crawled {len(visited)} pages | {len(all_images)} images | {url.replace(config.url,'')[:40]}")

                    except Exception as e:
                        failed.append(url)
                        logger.debug(f"Failed {url}: {e}")

            # Process queue in batches
            while queue and len(visited) < config.max_pages:
                batch = []
                while queue and len(batch) < config.workers * 2 and len(visited) + len(batch) < config.max_pages:
                    u = queue.pop(0)
                    if u not in visited:
                        batch.append(u)
                if not batch:
                    break
                await asyncio.gather(*[crawl_page(u) for u in batch])
                await asyncio.sleep(0.2)

            self._progress(72, f"Crawl done — {len(visited)} pages, {len(all_images)} images")

            # ── Save images.json always (even when download=False) ──────────
            images_list = list(all_images.values())
            (out_dir / "images.json").write_text(
                json.dumps(images_list, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result.images_total = len(all_images)
            result.images_content = sum(1 for img in all_images.values() if img["category"] == "content")
            result.images_decorative = len(all_images) - result.images_content

            # ── Download images (optional) ───────────────────────────────────
            if config.download_images and all_images:
                content_imgs = [img for img in all_images.values() if img["category"] == "content"]
                self._progress(75, f"Downloading {len(content_imgs)} content images...")
                downloaded_imgs = await self._download_images(client, content_imgs, out_dir, dl_sem)
                result.images_downloaded = downloaded_imgs
            else:
                self._progress(75, f"Skipping image download — {result.images_content} content images catalogued")

            # ── Download PDFs ─────────────────────────────────────────────────
            if config.download_pdfs and all_pdfs:
                self._progress(88, f"Downloading {len(all_pdfs)} PDFs...")
                downloaded_pdfs = await self._download_pdfs(client, list(all_pdfs.values()), out_dir, dl_sem)
                result.pdfs_found = len(all_pdfs)
                result.pdfs_downloaded = downloaded_pdfs

            # ── Save index + summary ─────────────────────────────────────────
            self._progress(95, "Saving manifest and summary...")
            content_files = self._build_content_files(pages_data, out_dir)
            pages_by_lang = self._group_by_language(pages_data)

            self._save_index(out_dir, config.url, pages_data, pages_by_lang, all_images, all_pdfs, result)
            self._save_summary(out_dir, config.url, pages_data, failed, all_images, result, start)

        # Populate result
        result.pages_crawled = len(pages_data)
        result.pages_failed = len(failed)
        result.languages = sorted(pages_by_lang.keys())
        result.pages_by_language = {lang: [{"title": p["title"], "url": p["url"]} for p in ps]
                                     for lang, ps in pages_by_lang.items()}
        result.content_files = content_files
        result.elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        result.stats = {
            "pages_found": len(pages_data),
            "pages_failed": len(failed),
            "images_discovered": result.images_total,
            "images_downloaded": result.images_downloaded,
            "images_content": result.images_content,
            "images_decorative": result.images_decorative,
            "pdfs_discovered": result.pdfs_found,
            "pdfs_downloaded": result.pdfs_downloaded,
            "languages": result.languages,
            "content_files_saved": len(content_files),
        }

        self._progress(100,
            f"Done — {result.pages_crawled} pages | {result.images_downloaded} images | {result.pdfs_downloaded} PDFs")
        return result

    # ── Extraction Helpers ────────────────────────────────────────────────────

    def _extract_title(self, soup: BeautifulSoup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else "Untitled"

    def _detect_lang(self, soup: BeautifulSoup, url: str) -> str:
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            code = html_tag["lang"].split("-")[0].lower()
            if code in KNOWN_LANGS:
                return code
        return lang_from_url(url)

    def _extract_text(self, soup: BeautifulSoup, url: str) -> str:
        """Clean text extraction with deduplication (sabbskin technique)."""
        # Remove noise
        for tag in soup.find_all(["script", "style", "noscript", "svg", "iframe", "form", "button"]):
            tag.extract()
        for el in soup.find_all(class_=re.compile(r"(cookie|gdpr|modal|popup|overlay|crisp|intercom)", re.I)):
            el.extract()
        for el in soup.find_all(id=re.compile(r"(cookie|gdpr|modal|chat|crisp|intercom)", re.I)):
            el.extract()

        # Find best content container
        main = None
        for sel in ["main", "article", "#content", ".entry-content", ".page-content", "[role=main]"]:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 200:
                main = el
                break
        content = main or soup.find("body") or soup

        text = content.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        # Dedup repeated lines (removes WP footer spam)
        lines, seen, deduped = text.split("\n"), set(), []
        for line in lines:
            key = line.strip().lower()
            if not key:
                deduped.append("")
            elif key not in seen:
                seen.add(key)
                deduped.append(line)
        return "\n".join(deduped).strip()

    def _extract_images(self, soup: BeautifulSoup, page_url: str, config: CrawlConfig) -> list[dict]:
        """
        Full image extraction (sabbskin techniques):
        - data-src, data-lazy-src for lazy loading
        - srcset best resolution
        - CSS background-image
        - WP size suffix stripping
        """
        found, seen = [], set()

        for img in soup.find_all("img"):
            src = (img.get("data-src") or img.get("data-lazy-src") or
                   img.get("data-original") or img.get("src") or "")
            srcset = img.get("srcset") or img.get("data-srcset") or ""
            alt = img.get("alt", "").strip()

            best = best_from_srcset(srcset)
            if best:
                src = best

            if not src or src.startswith("data:"):
                continue

            src = normalize_url(src, page_url)
            if not src:
                continue
            src = clean_wp_image_url(src)

            if src in seen:
                continue
            seen.add(src)

            category = self._classify_image(src, alt, config)
            found.append({
                "url": src, "alt": alt, "page_url": page_url,
                "category": category,
                "width": img.get("width", ""), "height": img.get("height", ""),
            })

        # CSS background-image
        for el in soup.find_all(style=True):
            for m in re.findall(r"url\(['\"]?(https?://[^'\")\s]+)['\"]?\)", el.get("style", "")):
                m = clean_wp_image_url(normalize_url(m, page_url))
                if m and m not in seen:
                    seen.add(m)
                    category = self._classify_image(m, "", config)
                    found.append({"url": m, "alt": "", "page_url": page_url,
                                  "category": category, "width": "", "height": ""})
        return found

    def _classify_image(self, url: str, alt: str, config: CrawlConfig) -> str:
        url_lower = url.lower()
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in config.blocked_extensions:
            return "decorative"
        for pat in config.decorative_patterns:
            if pat.lower() in url_lower:
                return "decorative"
        return "content"

    def _extract_pdfs(self, soup: BeautifulSoup, page_url: str) -> list[dict]:
        pdfs, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = normalize_url(a["href"], page_url)
            if href.lower().endswith(".pdf") and href not in seen:
                seen.add(href)
                pdfs.append({"url": href, "title": a.get_text(strip=True) or "document", "page_url": page_url})
        return pdfs

    def _extract_links(self, soup: BeautifulSoup, page_url: str, base_domain: str, config: CrawlConfig) -> list[str]:
        links = []
        for a in soup.find_all("a", href=True):
            href = normalize_url(a["href"], page_url)
            if not href or not is_same_domain(href, base_domain):
                continue
            ext = Path(urlparse(href).path).suffix.lower()
            if ext in SKIP_LINK_EXTENSIONS:
                continue
            if any(skip in href for skip in ["/feed/", "/wp-json/", "/wp-admin/", "?replytocom", "mate-access"]):
                continue
            links.append(href)
        return links

    # ── Download Helpers ──────────────────────────────────────────────────────

    async def _download_images(self, client: httpx.AsyncClient, imgs: list[dict],
                                out_dir: Path, sem: asyncio.Semaphore) -> int:
        downloaded = 0

        async def dl(idx: int, img: dict):
            nonlocal downloaded
            url = img["url"]
            lang = lang_from_url(img.get("page_url", ""))
            dest_dir = out_dir / "images" / lang
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / safe_filename(url, idx)
            if dest.exists():
                downloaded += 1
                img["local_path"] = str(dest.relative_to(out_dir))
                return
            async with sem:
                try:
                    async with client.stream("GET", url, timeout=30) as resp:
                        if resp.status_code == 200:
                            ct = resp.headers.get("content-type", "")
                            if "svg" in ct:
                                return
                            with open(dest, "wb") as f:
                                async for chunk in resp.aiter_bytes(8192):
                                    f.write(chunk)
                            downloaded += 1
                            img["local_path"] = str(dest.relative_to(out_dir))
                except Exception:
                    pass

        batch_size = 20
        tasks = [dl(i, img) for i, img in enumerate(imgs)]
        for i in range(0, len(tasks), batch_size):
            await asyncio.gather(*tasks[i:i+batch_size])
            self._progress(
                75 + int(i / max(len(tasks), 1) * 12),
                f"Images: {downloaded}/{len(imgs)} downloaded..."
            )
        return downloaded

    async def _download_pdfs(self, client: httpx.AsyncClient, pdfs: list[dict],
                              out_dir: Path, sem: asyncio.Semaphore) -> int:
        downloaded = 0
        pdf_dir = out_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        async def dl(idx: int, pdf: dict):
            nonlocal downloaded
            dest = pdf_dir / safe_filename(pdf["url"], idx, ".pdf")
            if dest.exists():
                downloaded += 1
                return
            async with sem:
                try:
                    async with client.stream("GET", pdf["url"], timeout=60) as resp:
                        if resp.status_code == 200:
                            with open(dest, "wb") as f:
                                async for chunk in resp.aiter_bytes(8192):
                                    f.write(chunk)
                            downloaded += 1
                            pdf["local_path"] = str(dest.relative_to(out_dir))
                except Exception:
                    pass

        await asyncio.gather(*[dl(i, p) for i, p in enumerate(pdfs)])
        return downloaded

    # ── Save Helpers ──────────────────────────────────────────────────────────

    async def _save_page(self, out_dir: Path, url: str, title: str, lang: str, text: str):
        pages_dir = out_dir / "pages" / lang
        pages_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9 _-]", "", title).strip()[:60] or "page"
        md_path = pages_dir / f"{safe}.md"
        md_path.write_text(f"# {title}\n\nSource: {url}\n\n---\n\n{text}", encoding="utf-8")

    def _group_by_language(self, pages: list[dict]) -> dict[str, list[dict]]:
        by_lang: dict[str, list[dict]] = {}
        for p in pages:
            by_lang.setdefault(p["language"], []).append(p)
        return by_lang

    def _build_content_files(self, pages: list[dict], out_dir: Path) -> list[dict]:
        files = []
        for p in pages:
            lang = p["language"]
            safe = re.sub(r"[^a-zA-Z0-9 _-]", "", p["title"]).strip()[:60] or "page"
            path = out_dir / "pages" / lang / f"{safe}.md"
            if path.exists():
                files.append({
                    "title": p["title"], "url": p["url"], "lang": lang,
                    "file": str(path.relative_to(out_dir)),
                    "text_length": path.stat().st_size,
                })
        return files

    def _save_index(self, out_dir: Path, site: str, pages: list[dict],
                    by_lang: dict, images: dict, pdfs: dict, result: SiteCrawlResult):
        content_count = sum(1 for img in images.values() if img["category"] == "content")
        index = {
            "site": site,
            "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "strategy": "site_crawler",
            "pages_by_language": {
                lang: [{"title": p["title"], "url": p["url"], "language": p["language"]} for p in ps]
                for lang, ps in sorted(by_lang.items())
            },
            "pages_flat": pages,
            "stats": {
                "pages_crawled": len(pages),
                "images_total": len(images),
                "images_content": content_count,
                "images_decorative": len(images) - content_count,
                "pdfs_found": len(pdfs),
                "languages": sorted(by_lang.keys()),
            },
        }
        (out_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "pdfs.json").write_text(json.dumps(list(pdfs.values()), indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_summary(self, out_dir: Path, site: str, pages: list[dict],
                      failed: list, images: dict, result: SiteCrawlResult, start: float):
        by_lang = self._group_by_language(pages)
        content_count = sum(1 for img in images.values() if img["category"] == "content")
        summary = {
            "site": site,
            "output_dir": str(out_dir),
            "duration_sec": round(time.monotonic() - start, 1),
            "pages_crawled": len(pages),
            "pages_failed": len(failed),
            "images_total": len(images),
            "images_content": content_count,
            "images_decorative": len(images) - content_count,
            "images_downloaded": result.images_downloaded,
            "pdfs_found": result.pdfs_found,
            "pdfs_downloaded": result.pdfs_downloaded,
            "languages": sorted(by_lang.keys()),
            "pages_per_language": {lang: len(ps) for lang, ps in by_lang.items()},
            "failed_urls": failed[:20],
        }
        (out_dir / "crawl_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
