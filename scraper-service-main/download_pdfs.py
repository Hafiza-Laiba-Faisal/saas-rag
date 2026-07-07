#!/usr/bin/env python3
"""
Tax.gov.ae VAT Documents Downloader - Working Solution
"""
import sys
import os
import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Load .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Configuration
DOWNLOAD_DIR = Path("tax_gov_ae_complete_pdfs")
DOWNLOAD_DIR.mkdir(exist_ok=True)

SEED_URLS = [
    "https://tax.gov.ae/en/vat.aspx",
    "https://tax.gov.ae/en/taxes/vat/guides.references.aspx",
    "https://tax.gov.ae/en/legislation.aspx",
    "https://tax.gov.ae/en/public.clarifications.aspx",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

visited = set()
pdf_urls = set()
downloaded = 0
failed = 0

# Functions
def download_pdf(url):
    global downloaded, failed
    
    filename = Path(url.split("/")[-1].split("?")[0])
    if not filename or len(str(filename)) < 3:
        filename = f"doc_{abs(hash(url)) % 100000}.pdf"
    
    filename = str(filename).replace("%20", "_")[:150]
    filepath = DOWNLOAD_DIR / filename
    
    if filepath.exists():
        return
    
    try:
        r = session.get(url, timeout=30, stream=True)
        if r.status_code == 200 and (r.content[:4] == b"%PDF" or "pdf" in r.headers.get("content-type", "")):
            filepath.write_bytes(r.content)
            downloaded += 1
            print(f"  ✅ [{downloaded:3d}] {filename} ({len(r.content)//1024}KB)")
            sys.stdout.flush()
        else:
            failed += 1
    except:
        failed += 1


def crawl_page(url, depth=0, max_depth=2):
    global visited, pdf_urls
    
    if url in visited or depth > max_depth or "tax.gov.ae" not in url:
        return
    
    visited.add(url)
    print(f"\n{'  '*depth}📄 [{len(visited)}] {url[:70]}")
    sys.stdout.flush()
    
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"{'  '*depth}  ❌ HTTP {r.status_code}")
            sys.stdout.flush()
            return
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        links_found = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(url, href)
            
            if ".pdf" in full_url.lower():
                if full_url not in pdf_urls:
                    pdf_urls.add(full_url)
                    links_found += 1
            elif depth < max_depth and "tax.gov.ae" in full_url and full_url not in visited:
                if any(kw in full_url.lower() for kw in ["vat", "guide", "legislation", "clarification"]):
                    time.sleep(0.3)
                    crawl_page(full_url, depth + 1, max_depth)
        
        if links_found:
            print(f"{'  '*depth}  🔗 {links_found} PDF links")
            sys.stdout.flush()
    
    except Exception as e:
        print(f"{'  '*depth}  ❌ {e}")
        sys.stdout.flush()


# Main
def main():
    print("=" * 80)
    print("🚀 Tax.gov.ae Complete VAT Documents Downloader")
    print("=" * 80)
    print(f"📁 Directory: {DOWNLOAD_DIR}\n")
    sys.stdout.flush()
    
    # Step 1: Crawl
    print("📊 STEP 1: Crawling for PDF links...\n")
    sys.stdout.flush()
    
    for seed in SEED_URLS:
        crawl_page(seed, depth=0, max_depth=2)
        time.sleep(1)
    
    print(f"\n📦 Total PDF URLs: {len(pdf_urls)}")
    print(f"📄 Pages visited: {len(visited)}\n")
    sys.stdout.flush()
    
    if not pdf_urls:
        print("⚠️  No PDFs found!")
        return
    
    # Step 2: Download
    print("⬇️  STEP 2: Downloading PDFs...\n")
    sys.stdout.flush()
    
    for pdf_url in sorted(pdf_urls):
        download_pdf(pdf_url)
        time.sleep(0.2)
    
    print("\n" + "=" * 80)
    print(f"✅ Downloaded: {downloaded} PDFs")
    print(f"❌ Failed: {failed}")
    print(f"📁 Location: {DOWNLOAD_DIR.absolute()}/")
    print("=" * 80)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
