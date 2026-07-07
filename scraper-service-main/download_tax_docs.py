#!/usr/bin/env python3
"""
Complete UAE VAT Documents Downloader
- Crawls tax.gov.ae and uaelegislation.gov.ae
- Uses DeepCrawl API as primary (if configured) or fallback on 403
- Downloads all PDFs found
"""
import requests
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# Load .env file
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

# Configuration
DOWNLOAD_DIR = Path("uae_vat_all_documents")
DOWNLOAD_DIR.mkdir(exist_ok=True)

DEEPCRAWL_API_KEY = os.environ.get("DEEPCRAWL_API_KEY")
USE_DEEPCRAWL_PRIMARY = bool(DEEPCRAWL_API_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)

downloaded = 0
visited_urls = set()
pdf_links = set()


def fetch_with_deepcrawl(url):
    """Fetch page content using DeepCrawl API."""
    if not DEEPCRAWL_API_KEY:
        return None
    
    try:
        payload = {
            "url": url,
            "includeHtml": True,
            "includeMarkdown": False,
            "includeMetadata": True,
            "includeLinks": True,
        }
        headers = {
            "Authorization": f"Bearer {DEEPCRAWL_API_KEY}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            "https://api.deepcrawl.dev/read",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            html = data.get("html") or data.get("cleanedHtml") or ""
            print(f"  🔓 DeepCrawl bypass successful ({len(html)} chars)")
            return html
        else:
            print(f"  ⚠️  DeepCrawl API error: {r.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ DeepCrawl error: {e}")
        return None


def fetch_page(url):
    """Fetch page with DeepCrawl primary/fallback logic."""
    # Primary: Use DeepCrawl if configured
    if USE_DEEPCRAWL_PRIMARY:
        print(f"  🌐 Fetching via DeepCrawl (primary)...")
        html = fetch_with_deepcrawl(url)
        if html:
            return html
        print(f"  ↻ Falling back to direct HTTP...")
    
    # Try direct HTTP
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            print(f"  ✅ Direct fetch: {r.status_code}")
            return r.text
        elif r.status_code in (403, 429):
            print(f"  🔒 Blocked: {r.status_code}")
            # Fallback to DeepCrawl
            if not USE_DEEPCRAWL_PRIMARY and DEEPCRAWL_API_KEY:
                print(f"  ↻ Trying DeepCrawl fallback...")
                html = fetch_with_deepcrawl(url)
                if html:
                    return html
            return None
        else:
            print(f"  ⚠️  HTTP {r.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def download_pdf(url, filename=None):
    """Download a PDF file."""
    global downloaded
    
    if not filename:
        filename = Path(urlparse(url).path).name
        if not filename or len(filename) < 3:
            filename = f"doc_{abs(hash(url)) % 100000}.pdf"
    
    filename = filename.replace("%20", "_").replace(" ", "_")
    filepath = DOWNLOAD_DIR / filename
    
    if filepath.exists():
        return False
    
    try:
        r = session.get(url, timeout=30, stream=True, allow_redirects=True)
        
        # If blocked, try DeepCrawl
        if r.status_code in (403, 429) and DEEPCRAWL_API_KEY:
            print(f"    🔒 Blocked, trying DeepCrawl...")
            html = fetch_with_deepcrawl(url)
            if html and html[:4] == "%PDF":
                filepath.write_text(html)
                downloaded += 1
                size_kb = filepath.stat().st_size // 1024
                print(f"    ✅ [{downloaded:3d}] {filename} ({size_kb}KB) via DeepCrawl")
                return True
        
        if r.status_code == 200:
            content_type = r.headers.get("content-type", "").lower()
            is_pdf = r.content[:4] == b"%PDF" or "pdf" in content_type
            
            if is_pdf:
                filepath.write_bytes(r.content)
                downloaded += 1
                size_kb = filepath.stat().st_size // 1024
                print(f"    ✅ [{downloaded:3d}] {filename} ({size_kb}KB)")
                return True
        
        return False
    except Exception as e:
        print(f"    ❌ {filename}: {e}")
        return False


def crawl_page(url, depth=0, max_depth=2):
    """Crawl a page and extract PDF links."""
    if url in visited_urls or depth > max_depth:
        return
    
    visited_urls.add(url)
    print(f"\n{'  ' * depth}📄 [{depth}] {url}")
    
    html = fetch_page(url)
    if not html:
        return
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract all PDF links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(url, href)
            
            # PDF direct links
            if ".pdf" in full_url.lower():
                if full_url not in pdf_links:
                    pdf_links.add(full_url)
                    print(f"{'  ' * (depth + 1)}🔗 PDF: {Path(urlparse(full_url).path).name}")
            
            # Follow relevant UAE gov pages
            elif depth < max_depth:
                parsed = urlparse(full_url)
                is_relevant = (
                    ("tax.gov.ae" in parsed.netloc or "uaelegislation.gov.ae" in parsed.netloc)
                    and any(kw in full_url.lower() for kw in ["vat", "guide", "legislation", "clarification", "law", "regulation"])
                    and full_url not in visited_urls
                )
                if is_relevant:
                    time.sleep(0.5)  # Rate limiting
                    crawl_page(full_url, depth + 1, max_depth)
        
        # Also check for legislation IDs (uaelegislation.gov.ae pattern)
        if "uaelegislation.gov.ae" in url:
            leg_ids = set(re.findall(r'/en/legislations/(\d+)', html))
            if leg_ids:
                print(f"{'  ' * (depth + 1)}📋 Found {len(leg_ids)} legislation IDs")
                for leg_id in leg_ids:
                    for lang in ["en", "ar"]:
                        pdf_url = f"https://uaelegislation.gov.ae/en/legislations/{leg_id}/download?language={lang}"
                        if pdf_url not in pdf_links:
                            pdf_links.add(pdf_url)
    
    except Exception as e:
        print(f"{'  ' * depth}❌ Parse error: {e}")


def main():
    print("=" * 80)
    print("🚀 UAE VAT Complete Documents Downloader")
    print("=" * 80)
    
    if USE_DEEPCRAWL_PRIMARY:
        print("✅ DeepCrawl API: PRIMARY mode")
    elif DEEPCRAWL_API_KEY:
        print("✅ DeepCrawl API: FALLBACK mode (403/429)")
    else:
        print("⚠️  DeepCrawl API: NOT configured")
    
    # Seed URLs
    seed_urls = [
        "https://tax.gov.ae/en/vat.aspx",
        "https://tax.gov.ae/en/taxes/vat/guides.references.aspx",
        "https://tax.gov.ae/en/legislation.aspx",
        "https://tax.gov.ae/en/public.clarifications.aspx",
        "https://uaelegislation.gov.ae/en/legislations",
        "https://uaelegislation.gov.ae/en/latest-legislations",
        "https://uaelegislation.gov.ae/en/legislations?sector=1",
    ]
    
    # Step 1: Crawl and collect PDF links
    print(f"\n📊 STEP 1: Crawling {len(seed_urls)} seed URLs...")
    for seed_url in seed_urls:
        crawl_page(seed_url, depth=0, max_depth=1)
        time.sleep(1)
    
    print(f"\n📦 Total PDF links collected: {len(pdf_links)}")
    
    if not pdf_links:
        print("\n⚠️  No PDF links found!")
        return
    
    # Step 2: Download all PDFs
    print(f"\n⬇️  STEP 2: Downloading {len(pdf_links)} PDFs...")
    print(f"   Location: {DOWNLOAD_DIR}/\n")
    
    for pdf_url in sorted(pdf_links):
        download_pdf(pdf_url)
        time.sleep(0.3)
    
    print("\n" + "=" * 80)
    print(f"✅ DONE! {downloaded} new PDFs downloaded")
    print(f"📁 Location: {DOWNLOAD_DIR.absolute()}/")
    print("=" * 80)


if __name__ == "__main__":
    main()
