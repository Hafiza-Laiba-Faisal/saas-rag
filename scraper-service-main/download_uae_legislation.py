#!/usr/bin/env python3
"""
UAE Legislation PDF Downloader
Crawls all sectors and downloads legislation PDFs (English + Arabic)
"""
import requests
import os
import re
import time
from pathlib import Path

# Load .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DIR = Path("uae_legislation_all_pdfs")
DIR.mkdir(exist_ok=True)

API_KEY = os.environ.get("DEEPCRAWL_API_KEY")
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

downloaded = 0
failed = 0
all_ids = set()


def fetch_with_deepcrawl(url):
    """Fetch using DeepCrawl API."""
    if not API_KEY:
        return None
    try:
        r = requests.post(
            "https://api.deepcrawl.dev/read",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"url": url, "includeHtml": True},
            timeout=60,
        )
        if r.status_code == 200:
            return r.json().get("html", "")
        print(f"    DeepCrawl error: {r.status_code}")
    except Exception as e:
        print(f"    DeepCrawl exception: {e}")
    return None


def download_pdf(leg_id, lang="en"):
    """Download PDF for legislation ID."""
    global downloaded, failed
    
    url = f"https://uaelegislation.gov.ae/en/legislations/{leg_id}/download?language={lang}"
    filename = f"leg_{leg_id}_{lang}.pdf"
    path = DIR / filename
    
    if path.exists():
        return
    
    try:
        # Try direct first
        r = session.get(url, timeout=30, stream=True)
        
        if r.status_code == 200 and (r.content[:4] == b"%PDF" or "pdf" in r.headers.get("content-type", "")):
            path.write_bytes(r.content)
            downloaded += 1
            print(f"  ✅ [{downloaded:3d}] {filename} ({len(r.content)//1024}KB)")
            return
        
        # If 403, try DeepCrawl
        if r.status_code in (403, 429) and API_KEY:
            html = fetch_with_deepcrawl(url)
            if html and html[:4] == "%PDF":
                path.write_text(html)
                downloaded += 1
                print(f"  ✅ [{downloaded:3d}] {filename} (DeepCrawl)")
                return
        
        failed += 1
    except Exception as e:
        failed += 1


def collect_ids_from_page(url):
    """Collect legislation IDs from a page."""
    print(f"\n📄 {url}")
    
    # Try direct first
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            print("  ✅ Direct fetch")
            html = r.text
        elif r.status_code in (403, 429):
            print("  🔒 Blocked, trying DeepCrawl...")
            html = fetch_with_deepcrawl(url)
            if not html:
                print("  ❌ Failed")
                return set()
            print("  🔓 DeepCrawl success")
        else:
            print(f"  ❌ HTTP {r.status_code}")
            return set()
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return set()
    
    # Extract IDs
    ids = set(re.findall(r'/en/legislations/(\d+)', html))
    print(f"  📋 Found {len(ids)} IDs")
    return ids


print("=" * 80)
print("🚀 UAE Legislation Complete PDF Downloader")
print("=" * 80)
print(f"{'✅' if API_KEY else '❌'} DeepCrawl API: {'Configured' if API_KEY else 'Not configured'}")
print()

# Step 1: Collect all legislation IDs
print("📊 STEP 1: Collecting legislation IDs from all pages...")

# Main pages
main_urls = [
    "https://uaelegislation.gov.ae/en/legislations",
    "https://uaelegislation.gov.ae/en/latest-legislations",
    "https://uaelegislation.gov.ae/en/most-viewed-legislations",
    "https://uaelegislation.gov.ae/en/archived-legislation",
    "https://uaelegislation.gov.ae/en/constitution",
]

for url in main_urls:
    ids = collect_ids_from_page(url)
    all_ids.update(ids)
    time.sleep(1)

# All sectors (1-61)
print("\n📋 Checking all sectors (1-61)...")
for sector in range(1, 62):
    url = f"https://uaelegislation.gov.ae/en/legislations?sector={sector}"
    ids = collect_ids_from_page(url)
    if ids:
        all_ids.update(ids)
    time.sleep(0.5)

print(f"\n📦 Total unique legislation IDs: {len(all_ids)}")

if all_ids:
    # Step 2: Download all PDFs
    print(f"\n⬇️  STEP 2: Downloading PDFs for {len(all_ids)} legislations (EN + AR)...")
    print(f"   Total PDFs to download: {len(all_ids) * 2}\n")
    
    sorted_ids = sorted(all_ids, key=int)
    for i, leg_id in enumerate(sorted_ids, 1):
        print(f"[{i}/{len(sorted_ids)}] Legislation {leg_id}:")
        download_pdf(leg_id, "en")
        download_pdf(leg_id, "ar")
        time.sleep(0.2)

print("\n" + "=" * 80)
print(f"✅ Downloaded: {downloaded} PDFs")
print(f"❌ Failed: {failed}")
print(f"📁 Location: {DIR.absolute()}/")
print("=" * 80)
