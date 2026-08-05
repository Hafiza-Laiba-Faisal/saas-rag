"""
Grand Hotel de la Ville - Full Site Scraper
Scrapes all pages, images, and PDFs.
Uses sabbskin-style proven image extraction techniques.
"""
import os, re, json, time, hashlib, asyncio, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import httpx
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL = "https://www.grandhoteldelaville.com"
OUTPUT_DIR = Path("crawl_output/grandhotel_full")
MAX_PAGES = 300
WORKERS = 6

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}

KNOWN_LANGS = {"it", "en", "fr", "de", "es"}

# Decorative image patterns (sabbskin approach)
DECORATIVE_PATTERNS = [
    "logo", "favicon", "icon", "facebook", "instagram", "twitter",
    "whatsapp", "youtube", "tiktok", "social", "footer-logo",
    "button", "badge", "tracking", "pixel", "separator",
    "spinner", "arrow", "chevron", "close-", "hamburger",
    "facebook_square", "instagram1", "logo_footer", "logo_dark",
    "logo.png", "logo-", "dummy", "bordo", "marker", "placeholder",
    "Group-19", "Group-20", "Group-196", "Group-197", "Group-198",
    "Rectangle", "divano_mobile", "letto_mobile",
]
BLOCKED_EXTENSIONS = {".svg", ".ico", ".gif", ".webp"}
SKIP_DOMAINS = ["cdn.shopify.com", "googletagmanager.com", "facebook.com"]

# ── State ────────────────────────────────────────────────────────────────────
visited_urls: set[str] = set()
queued_urls: set[str] = set()
all_images: dict[str, dict] = {}   # url -> {url, alt, page_url, category}
all_pdfs: dict[str, dict] = {}     # url -> {url, title, page_url}
pages_data: list[dict] = []
failed_urls: list[str] = []

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_url(url: str, base: str = BASE_URL) -> str:
    """Normalize URL to absolute, strip fragments and tracking params."""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = BASE_URL + url
    if not url.startswith("http"):
        url = urljoin(base, url)
    # Strip fragment
    url = url.split("#")[0]
    # Strip common tracking params
    for param in ["utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"]:
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    url = url.rstrip("?&")
    return url.rstrip("/") if url != BASE_URL else url


def is_same_domain(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() in ("www.grandhoteldelaville.com", "grandhoteldelaville.com")


def lang_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    first = path.split("/")[0] if path else ""
    return first if first in KNOWN_LANGS else "it"


def is_decorative(url: str, alt: str = "") -> bool:
    url_lower = url.lower()
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return True
    for pat in DECORATIVE_PATTERNS:
        if pat in url_lower:
            return True
    return False


def best_src_from_srcset(srcset: str) -> str:
    """Get highest resolution URL from srcset (sabbskin technique)."""
    if not srcset:
        return ""
    parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
    return parts[-1] if parts else ""


def clean_wp_image_url(url: str) -> str:
    """Strip WordPress size suffixes: -300x200 -> full size."""
    # Remove -WxH suffix before extension
    url = re.sub(r"-\d+x\d+(\.[a-zA-Z]+)$", r"\1", url)
    # Remove size query params
    url = re.sub(r"[?&](w|h|width|height|size|resize)=\d+", "", url)
    return url.rstrip("?&")


def extract_images_from_soup(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Extract all images using sabbskin-style extraction:
    - data-src / data-srcset for lazy loading
    - srcset for best resolution
    - WP size suffix stripping
    """
    found = []
    seen = set()

    for img in soup.find_all("img"):
        # Try all src attributes (lazy loading support)
        src = (
            img.get("data-src") or
            img.get("data-lazy-src") or
            img.get("data-original") or
            img.get("src") or ""
        )
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        alt = img.get("alt", "").strip()
        width = img.get("width", "")
        height = img.get("height", "")

        # Prefer highest res from srcset
        if srcset:
            best = best_src_from_srcset(srcset)
            if best:
                src = best

        if not src or src.startswith("data:"):
            continue

        src = normalize_url(src, page_url)
        src = clean_wp_image_url(src)

        # Skip external domains
        parsed = urlparse(src)
        if any(d in parsed.netloc for d in SKIP_DOMAINS):
            continue

        if src in seen:
            continue
        seen.add(src)

        category = "decorative" if is_decorative(src, alt) else "content"

        found.append({
            "url": src,
            "alt": alt,
            "page_url": page_url,
            "category": category,
            "width": str(width),
            "height": str(height),
        })

    # Also check CSS background-image style attrs
    for el in soup.find_all(style=True):
        style = el.get("style", "")
        matches = re.findall(r"url\(['\"]?(https?://[^'\")\s]+)['\"]?\)", style)
        for m in matches:
            m = clean_wp_image_url(m)
            if m not in seen and not m.startswith("data:"):
                seen.add(m)
                category = "decorative" if is_decorative(m) else "content"
                found.append({
                    "url": m, "alt": "", "page_url": page_url,
                    "category": category, "width": "", "height": "",
                })

    return found


def extract_links_from_soup(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Extract all internal links."""
    links = []
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"], page_url)
        if href and is_same_domain(href):
            # Skip non-HTML resources
            ext = Path(urlparse(href).path).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
                           ".css", ".js", ".xml", ".zip", ".pdf"}:
                links.append(href)
    return links


def extract_pdfs_from_soup(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Extract PDF links."""
    pdfs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"], page_url)
        if href.lower().endswith(".pdf") and href not in seen:
            seen.add(href)
            pdfs.append({
                "url": href,
                "title": a.get_text(strip=True) or "document",
                "page_url": page_url,
            })
    return pdfs


def clean_text_from_soup(soup: BeautifulSoup, page_url: str) -> str:
    """Extract clean text using sabbskin-style approach."""
    # Remove noise elements
    for tag in soup.find_all(["script", "style", "noscript", "svg",
                               "iframe", "form", "button", "select"]):
        tag.extract()
    for el in soup.find_all(class_=re.compile(r"(cookie|gdpr|modal|popup|overlay|chat|crisp|intercom|floating)", re.I)):
        el.extract()
    for el in soup.find_all(id=re.compile(r"(cookie|gdpr|modal|chat|crisp|intercom)", re.I)):
        el.extract()

    # Find main content
    main = None
    for sel in ["main", "article", "#content", ".entry-content", ".page-content", "[role=main]"]:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 200:
            main = el
            break

    content = main if main else soup.find("body") or soup

    # Get clean text
    text = content.get_text(separator="\n", strip=True)
    # Collapse repeated whitespace/newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Dedup repeated lines (WP footer spam)
    lines = text.split("\n")
    seen_lines = set()
    deduped = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            deduped.append("")
            continue
        key = stripped.lower()
        if key not in seen_lines:
            seen_lines.add(key)
            deduped.append(line)

    return "\n".join(deduped).strip()


async def download_file(client: httpx.AsyncClient, url: str, dest: Path, semaphore: asyncio.Semaphore) -> bool:
    """Download a single file with semaphore rate limiting."""
    if dest.exists():
        return True
    async with semaphore:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with client.stream("GET", url, timeout=30) as resp:
                if resp.status_code == 200:
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
                    return True
        except Exception as e:
            pass
    return False


def safe_filename(url: str, idx: int, ext_override: str = "") -> str:
    """Generate safe filename from URL (sabbskin technique)."""
    path = urlparse(url).path
    name = path.split("/")[-1].split("?")[0]
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    if not name or "." not in name:
        ext = ext_override or ".jpg"
        h = hashlib.md5(url.encode()).hexdigest()[:8]
        name = f"image_{idx:04d}_{h}{ext}"
    return name


# ── Main Scraper ──────────────────────────────────────────────────────────────

async def scrape_all_pages():
    """Crawl all pages of the site."""
    print(f"\n{'='*60}")
    print(f"  Grand Hotel de la Ville — Full Scraper")
    print(f"  {BASE_URL}")
    print(f"{'='*60}\n")

    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=30,
        limits=limits
    ) as client:

        # Seed URLs
        seed_urls = [BASE_URL + "/"]
        # Add language variants explicitly
        for lang in ["en", "fr", "de", "es"]:
            seed_urls.append(f"{BASE_URL}/{lang}/")

        queue = list(seed_urls)
        for u in seed_urls:
            queued_urls.add(normalize_url(u))

        semaphore = asyncio.Semaphore(WORKERS)

        async def crawl_page(url: str):
            if url in visited_urls:
                return
            visited_urls.add(url)

            try:
                async with semaphore:
                    resp = await client.get(url, timeout=25)
                if resp.status_code != 200:
                    failed_urls.append(url)
                    return

                html = resp.text
                soup = BeautifulSoup(html, "html.parser")

                # Title
                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else urlparse(url).path

                # Language
                lang = lang_from_url(url)
                html_tag = soup.find("html")
                if html_tag and html_tag.get("lang"):
                    detected = html_tag["lang"].split("-")[0]
                    if detected in KNOWN_LANGS:
                        lang = detected

                # Clean text
                text = clean_text_from_soup(soup, url)

                # Images
                imgs = extract_images_from_soup(soup, url)
                for img in imgs:
                    if img["url"] not in all_images:
                        all_images[img["url"]] = img

                # PDFs
                pdfs = extract_pdfs_from_soup(soup, url)
                for pdf in pdfs:
                    if pdf["url"] not in all_pdfs:
                        all_pdfs[pdf["url"]] = pdf

                # Collect new links
                links = extract_links_from_soup(soup, url)
                new_count = 0
                for link in links:
                    if link not in queued_urls and link not in visited_urls:
                        if len(queued_urls) < MAX_PAGES:
                            queued_urls.add(link)
                            queue.append(link)
                            new_count += 1

                pages_data.append({
                    "url": url,
                    "title": title,
                    "language": lang,
                    "word_count": len(text.split()),
                    "images_on_page": len(imgs),
                    "new_links_found": new_count,
                })

                print(f"  ✅ [{len(visited_urls):3d}] {url.replace(BASE_URL, '')[:55]:<55} | "
                      f"{len(text.split()):4d} words | {len(imgs):3d} imgs | {new_count} new links")

                # Save page content
                await save_page(url, title, lang, text, soup)

            except Exception as e:
                failed_urls.append(url)
                print(f"  ❌ {url.replace(BASE_URL, '')[:60]} — {e}")

        # Process queue
        print(f"[1/3] Crawling pages (max {MAX_PAGES})...\n")
        i = 0
        while queue and len(visited_urls) < MAX_PAGES:
            batch = []
            while queue and len(batch) < WORKERS * 2:
                url = queue.pop(0)
                norm = normalize_url(url)
                if norm not in visited_urls:
                    batch.append(norm)

            if not batch:
                break

            tasks = [crawl_page(u) for u in batch]
            await asyncio.gather(*tasks)
            await asyncio.sleep(0.3)  # Polite delay

        print(f"\n  📊 Pages crawled: {len(visited_urls)} | Failed: {len(failed_urls)}")
        print(f"  🖼  Images found: {len(all_images)} | PDFs found: {len(all_pdfs)}")

        # Download images
        await download_images(client)

        # Download PDFs
        await download_pdfs(client)

    return pages_data


async def save_page(url: str, title: str, lang: str, text: str, soup: BeautifulSoup):
    """Save page content to disk."""
    pages_dir = OUTPUT_DIR / "pages" / lang
    pages_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", title).strip()[:50] or "page"
    md_path = pages_dir / f"{safe_name}.md"

    content = f"# {title}\n\nSource: {url}\n\n---\n\n{text}"
    md_path.write_text(content, encoding="utf-8")


async def download_images(client: httpx.AsyncClient):
    """Download all content images."""
    content_imgs = [img for img in all_images.values() if img["category"] == "content"]
    decorative_imgs = [img for img in all_images.values() if img["category"] == "decorative"]

    print(f"\n[2/3] Downloading images...")
    print(f"  Content images: {len(content_imgs)}")
    print(f"  Decorative (skipped): {len(decorative_imgs)}")

    if not content_imgs:
        print("  ⚠ No content images to download")
        return

    sem = asyncio.Semaphore(8)
    downloaded = 0
    skipped = 0
    failed = 0

    async def dl_img(idx: int, img: dict):
        nonlocal downloaded, skipped, failed
        url = img["url"]
        lang = lang_from_url(img.get("page_url", ""))
        img_dir = OUTPUT_DIR / "images" / lang
        img_dir.mkdir(parents=True, exist_ok=True)

        filename = safe_filename(url, idx)
        dest = img_dir / filename

        if dest.exists():
            skipped += 1
            return

        async with sem:
            try:
                async with client.stream("GET", url, timeout=30) as resp:
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type", "")
                        # Skip SVG even if not caught by extension check
                        if "svg" in content_type:
                            return
                        with open(dest, "wb") as f:
                            async for chunk in resp.aiter_bytes(8192):
                                f.write(chunk)
                        downloaded += 1
                        img["local_path"] = str(dest.relative_to(OUTPUT_DIR))
                    else:
                        failed += 1
            except Exception as e:
                failed += 1

    tasks = [dl_img(i, img) for i, img in enumerate(content_imgs)]
    # Process in batches to show progress
    batch_size = 20
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        await asyncio.gather(*batch)
        print(f"  ↳ Downloaded {min(i+batch_size, len(tasks))}/{len(content_imgs)}...")

    print(f"  ✅ Images: {downloaded} downloaded | {skipped} skipped | {failed} failed")


async def download_pdfs(client: httpx.AsyncClient):
    """Download all PDFs."""
    pdfs = list(all_pdfs.values())
    print(f"\n[3/3] Downloading PDFs ({len(pdfs)})...")

    if not pdfs:
        print("  No PDFs found")
        return

    sem = asyncio.Semaphore(4)
    pdf_dir = OUTPUT_DIR / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    async def dl_pdf(idx: int, pdf: dict):
        nonlocal downloaded
        url = pdf["url"]
        filename = safe_filename(url, idx, ".pdf")
        dest = pdf_dir / filename
        if dest.exists():
            return
        async with sem:
            try:
                async with client.stream("GET", url, timeout=60) as resp:
                    if resp.status_code == 200:
                        with open(dest, "wb") as f:
                            async for chunk in resp.aiter_bytes(8192):
                                f.write(chunk)
                        downloaded += 1
                        pdf["local_path"] = str(dest.relative_to(OUTPUT_DIR))
            except Exception:
                pass

    await asyncio.gather(*[dl_pdf(i, p) for i, p in enumerate(pdfs)])
    print(f"  ✅ PDFs: {downloaded}/{len(pdfs)} downloaded")


def save_results():
    """Save all results to JSON files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Group pages by language
    pages_by_language: dict[str, list] = {}
    for p in pages_data:
        lang = p["language"]
        pages_by_language.setdefault(lang, []).append(p)

    # images.json
    images_list = list(all_images.values())
    (OUTPUT_DIR / "images.json").write_text(
        json.dumps(images_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # pdfs.json
    (OUTPUT_DIR / "pdfs.json").write_text(
        json.dumps(list(all_pdfs.values()), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # index.json
    content_count = sum(1 for img in all_images.values() if img["category"] == "content")
    decorative_count = len(all_images) - content_count

    index = {
        "site": BASE_URL,
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strategy": "full_recursive",
        "pages_by_language": {
            lang: [{"title": p["title"], "url": p["url"]} for p in pages]
            for lang, pages in sorted(pages_by_language.items())
        },
        "pages_flat": pages_data,
        "stats": {
            "pages_crawled": len(pages_data),
            "pages_failed": len(failed_urls),
            "images_total": len(all_images),
            "images_content": content_count,
            "images_decorative": decorative_count,
            "pdfs_found": len(all_pdfs),
            "languages": sorted(pages_by_language.keys()),
        },
    }
    (OUTPUT_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # crawl_summary.json
    summary = {
        "site": BASE_URL,
        "output_dir": str(OUTPUT_DIR),
        "pages_crawled": len(pages_data),
        "pages_failed": len(failed_urls),
        "images_total": len(all_images),
        "images_content": content_count,
        "images_decorative": decorative_count,
        "pdfs_found": len(all_pdfs),
        "languages": sorted(pages_by_language.keys()),
        "pages_per_language": {lang: len(pages) for lang, pages in pages_by_language.items()},
        "failed_urls": failed_urls[:20],
    }
    (OUTPUT_DIR / "crawl_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'='*60}")
    print(f"  ✅ CRAWL COMPLETE")
    print(f"{'='*60}")
    print(f"  📄 Pages:      {len(pages_data)} crawled | {len(failed_urls)} failed")
    print(f"  🌍 Languages:  {sorted(pages_by_language.keys())}")
    print(f"  🖼  Images:     {len(all_images)} total | {content_count} content | {decorative_count} decorative")
    print(f"  📑 PDFs:       {len(all_pdfs)} found")
    print(f"  📁 Output:     {OUTPUT_DIR}/")
    print(f"{'='*60}\n")

    print(f"  Pages per language:")
    for lang, pages in sorted(pages_by_language.items()):
        print(f"    {lang}: {len(pages)} pages")


async def main():
    start = time.time()
    await scrape_all_pages()
    save_results()
    elapsed = time.time() - start
    print(f"\n  ⏱  Total time: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
