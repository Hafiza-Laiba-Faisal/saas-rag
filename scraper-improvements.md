# Scraper Improvements

## Overview

Three major improvements made to the web scraper for reliable full-site scraping of modern websites.

---

## 1. Playwright Fetcher (JS Rendering + Cloudflare Bypass)

**File:** `src/rbs_rag/scraper/fetcher/playwright_fetcher.py` (new)

Headless Chromium browser that renders JavaScript and bypasses aggressive anti-bot protections (Cloudflare, etc.).

- Full JS execution (booking widgets, SPAs, dynamic content)
- Anti-detection: `navigator.webdriver` spoofed, realistic UA, viewport, locale
- No chromedriver needed — uses Playwright's bundled browser
- Auto-imported as 3rd-tier fallback in `HTTPFetcher`

### Fallback Chain (`http_fetcher.py`)

```
Request URL
    │
    ├─ Tier 1: httpx (fast, lightweight)
    │     Cloudflare challenge or 403/429/503?
    │         │
    │         ├─ Tier 2: curl_cffi (TLS fingerprint bypass)
    │               Cloudflare challenge or empty/error?
    │                   │
    │                   └─ Tier 3: Playwright (full browser)
    │
    └── Content quality gate (engine.py)
         - Rejects text with >3% replacement chars (�)
         - Rejects text with <80% printable chars
         - Falls through to DeepCrawl API if available
```

This ensures:
- Simple sites → fastest path (httpx)
- Cloudflare sites → curl_cffi (fast TLS bypass)
- JS-heavy/aggressive sites → Playwright (full browser)
- Garbled/obfuscated content → DeepCrawl or failure

### Cloudflare Detection
`HTTPFetcher._is_cloudflare_challenge()` checks response body for patterns:
- `__cf_chl_`, `cf_chl_opt`, `challenge-form`
- `cf-browser-verification`, `cdn-cgi/challenge-platform`
- Applied after both httpx and curl_cffi tiers
- Detected challenges trigger automatic fallback to next tier

---

## 2. URL Deduplication

**File:** `src/rbs_rag/scraper/core/engine.py` — `_normalize_url()` method (line ~352)

Before: Same page scraped multiple times because of:
- `/page#main-content` vs `/page`
- `/room/n-1?info[...]&utm_source=...` vs `/room/n-1`
- `/rooms.en` vs `/rooms`

Now `_normalize_url()`:
- Strips fragments (`#main-content`, `#section`)
- Filters tracking params (`utm_*`, `fbclid`, `gclid`, `info[*]`)
- Removes language suffixes (`.en`, `.fr`, `.es`, `.it`, `.de`) from paths
- Sorts remaining query params for consistent keys

Result: `/room/n-1?info[...]` and `/room/n-1#main-content` both normalize to `/room/n-1`.

---

## 3. Full Site Scrape Mode

**File:** `src/rbs_rag/web/server.py` — `ScrapeRequest.full_site`
**File:** `src/rbs_rag/scraper/core/engine.py` — `crawl_domain(full_site=True)`

- `ScrapeRequest.full_site: bool` (default `False`)
- When enabled:
  - Raises limits: `max_pages=min(max(200, user), 500)`, `max_depth=min(max(10, user), 20)`
  - Parallel scraping with semaphore (5 concurrent) and time cap (2min max)
  - Falls back to BFS crawl with normalized URL dedup

---

## 4. New Methods for Smart Discovery & Parallel Scraping

All in `src/rbs_rag/scraper/core/engine.py`:

### `_parse_sitemap(base_url)` (line ~184)
- Tries multiple sitemap candidates (`/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`)
- Follows sub-sitemaps (sitemap indexes) recursively
- Uses the Fetcher (with Cloudflare bypass) instead of a separate httpx client

### `_is_crawlable(url, base_domain)` (line ~233)
- Filters out non-HTML resources (`.jpg`, `.pdf`, `.zip`, `.mp4`, fonts, etc.)
- Blocks social share URLs (`/sharer/`, `pinterest.com/pin/`, `linkedin.com/share`, `twitter.com/intent/`)
- Validates scheme (must start with `http`)
- Checks domain matches `base_domain`

### `_discover_language_variants(base_url, base_domain)` (line ~247)
- Extracts hreflang `<link rel="alternate" hreflang="..." href="..." />` tags
- Fallback: detects `/en/`, `/fr/`, `/de/`, `/es/` path prefixes in page links
- Returns normalized set of language-specific URLs

### `_discover_urls(start_url, max_pages, max_depth)` (line ~280)
- **Tier 1:** Sitemap parsing (fastest path — gets all pages in one shot)
- **Tier 2 (fallback):** BFS crawl starting from `start_url`
- If sitemap is found, also discovers language variants from hreflang tags
- Filters through `_is_crawlable()` and normalizes with `_normalize_url()`
- Caps at `max_pages`

### `scrape_all(urls, max_concurrent=5, time_cap=60)` (line ~330)
- Parallel scraping with `asyncio.Semaphore(max_concurrent)`
- `asyncio.wait_for(time_cap)` enforces a hard time limit
- Gracefully handles exceptions per-URL via `return_exceptions=True`

---

## Frontend Changes

- `index.html`: Fixed hardcoded `max_depth: 2` → now reads from `#maxDepthInput`
- Both HTML files: Added "Full site" checkbox (`#fullSiteToggle`)
- `maxDepthInput` range: `1-10` (was `1-5`)

---

## Test Results (Final — Jul 16, 2026)

### Test 1: `https://www.palazzogaribaldiparma.com/en` (Cloudflare protected)

| Metric | Value |
|--------|-------|
| Total URLs scraped | **80 URLs in 48s** |
| Successful | **79/80** (98.75%) |
| Time cap | auto (120s) — completed in 48s |
| Sitemap | ✅ 79 URLs discovered |
| Language variants | ✅ EN, IT, FR, DE, ES (home + all rooms/services each) |
| Duplicates | 0 (normalized) |
| Social share URLs | 0 (filtered) |
| File/asset URLs | 0 (filtered) |

Pages include: home (all 5 languages), room pages (n.1–n.7 × 5 languages), rooms listing (3 languages), services/room services (all langs), food & wine (all langs), beauty & wellness (all langs), surroundings (all langs), contact (all langs), privacy/legal, cookies.

### Test 2: `https://www.grandhoteldelaville.com/` (standard site)

| Metric | Value |
|--------|-------|
| Total URLs scraped | **20 URLs in 37s** |
| Successful | **20/20** (100%) |
| Sitemap | ✅ 16 URLs from sub-sitemaps (page, product, product_cat) |
| Language variants | ✅ EN, FR, DE, ES (home pages discovered) |
| Duplicates | 0 |
| Social share URLs | 0 |

Pages include: home (5 languages), bar, restaurant, meeting rooms, fitness, rooms (classic, executive, junior suite, king, imperiale, matrimoniale tokio), contact, shop, footer.

---

## Files Modified

| File | Change |
|------|--------|
| `src/rbs_rag/scraper/fetcher/playwright_fetcher.py` | **New** — Playwright browser fetcher |
| `src/rbs_rag/scraper/fetcher/http_fetcher.py` | Added Playwright fallback tier, Cloudflare challenge detection (`_is_cloudflare_challenge()`) |
| `src/rbs_rag/scraper/core/engine.py` | Added `_normalize_url()`, `_is_crawlable()`, `_parse_sitemap()`, `_discover_language_variants()`, `_discover_urls()`, `scrape_all()`, `_is_clean_text()`, refactored `crawl_domain()` |
| `src/rbs_rag/scraper/extractors/readability.py` | Better `<span>` extraction, fallback to `soup.get_text()`, expanded tag list |
| `src/rbs_rag/services/scraper_service.py` | Added `full_site` to `ScrapeJob` and `crawl_url()` |
| `src/rbs_rag/web/server.py` | Added `full_site` field to `ScrapeRequest` |
| `src/rbs_rag/web/static/index.html` | Added full-site checkbox, fixed max_depth bug |
| `src/rbs_rag/web/static/client.html` | Added full-site checkbox |
