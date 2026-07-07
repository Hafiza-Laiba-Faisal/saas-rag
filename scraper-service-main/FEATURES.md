# Features

# Features

## ✅ Production-Grade Recursive Web Crawler

### Full Pipeline Architecture
Every crawl request passes through a 6-stage isolated pipeline:

| Stage | Module | Responsibility |
|-------|--------|----------------|
| Fetch | `core/fetcher/httpx_fetcher.py` | HTTP request, redirects, SSL, timeout |
| Content Detection | `core/content/detector.py` | Detect content type (HTML, PDF, images, videos, Office docs) |
| Detect | `core/detectors/` | Detect page conditions (login wall, Cloudflare, captcha, JS-only) |
| Parse | `core/parser/bs4_parser.py` | Convert raw HTML into a parse tree |
| Extract | `core/extractor/` | Pull structured data from parse tree |
| Format | `core/formatter/` | Convert output to JSON or Markdown |

### Recursive Crawler Features ✨

#### URL Discovery & Management
- **Queue-based scheduling** — priority queue with thread-safe operations
- **URL normalization** — `example.com/page`, `example.com/page/`, `example.com/page#section` all deduplicated
- **Depth control** — configurable max depth from seed URL
- **Domain filtering** — whitelist/blacklist support
- **robots.txt compliance** — honors robots.txt rules
- **Sitemap discovery** — extracts sitemap URLs from robots.txt

#### Content Type Detection
Automatically detects and handles:
- **HTML pages** — full extraction pipeline
- **PDF documents** — text extraction with OCR fallback
- **Images** — metadata, dimensions, EXIF, OCR
- **Videos** — metadata extraction
- **Office documents** — Word, Excel, PowerPoint
- **Archives** — ZIP, RAR, 7z
- **JSON/XML** — structured data

#### Intelligent Processing
- **Deduplication** — never fetches same URL twice
- **Query param filtering** — strips tracking params (utm_*, fbclid, etc)
- **Redirect following** — handles 301/302 redirects
- **Error handling** — structured error tracking per URL
- **Progress tracking** — real-time progress callbacks

#### Background Jobs
- Background job execution with progress polling
- Thread-safe job store (supports 50 concurrent jobs)
- Real-time statistics:
  - Total pages crawled
  - Success/failure counts
  - Content type distribution (HTML, PDF, images, etc)
  - Pages per second
  - Crawl depth reached

### Endpoints

#### Single Page Crawl
```
POST /crawl                    body: {"url": "...", "format": "json|markdown"}
GET  /crawl/test?url=...&format=...   quick browser/Swagger test
```

#### Recursive Site Crawl
```
POST /crawl/recursive          Start full site crawl
  body: {
    "url": "https://example.com",
    "max_depth": 3,              # Max crawl depth
    "max_pages": 100,            # Max pages to crawl
    "allowed_domains": null,     # Whitelist (null = seed domain only)
    "blocked_domains": [],       # Blacklist
    "respect_robots": true,      # Honor robots.txt
    "timeout": 30                # Request timeout
  }
  
GET  /crawl/recursive/status/{job_id}   Poll for progress
GET  /crawl/recursive/jobs              List all crawl jobs
DELETE /crawl/recursive/{job_id}        Delete job
```

### Response Envelope
Every endpoint returns a consistent structure:
```json
{
  "success": true,
  "data": {
    "pages": [
      {
        "url": "https://example.com/page1",
        "status": 200,
        "content_type": "html",
        "title": "Page Title",
        "depth": 1,
        "links_found": 25,
        "elapsed_ms": 234
      }
    ],
    "stats": {
      "total_pages": 100,
      "successful": 98,
      "failed": 2,
      "html_pages": 85,
      "pdf_files": 10,
      "images": 3,
      "total_time_sec": 45.2,
      "pages_per_second": 2.21
    }
  },
  "errors": [],
  "metrics": {
    "fetch_time_ms": 2303,
    "parse_time_ms": 83,
    "extract_time_ms": 8
  }
}
```

### Extractors
- **MetadataExtractor** — title, description, og:title, og:image, og:url, canonical
- **LinksExtractor** — all anchor hrefs, deduped, with domain + PDF flag
- **PDFExtractor** — text extraction with OCR fallback for scanned documents
- **ImageExtractor** — dimensions, format, EXIF, OCR text

### Detectors
Detectors only detect — they never attempt bypasses:
- `LoginRequiredDetector` — Facebook login wall, generic login pages
- `CloudflareDetector` — Cloudflare challenge pages
- `CaptchaDetector` — reCAPTCHA, hCaptcha
- `JavaScriptRequiredDetector` — JS-gated pages

---

## General Web Crawler — `/crawl`

---

## Facebook Post Scraper

### Core Scraping
- Scrapes **posts and reels** from any Facebook page
- Extracts captions, media URLs, post URLs, like/comment counts, timestamps
- Primary: JSON blob extraction from page source (3 strategies)
- Fallback: Selenium DOM extraction via JavaScript
- DASH manifest parsing for reels — separate video + audio URLs
- `efg` base64 param decoding to filter audio-only DASH segments
- Date range filtering (`date_from` / `date_to`)
- Configurable `max_posts` and `scroll_rounds` including unlimited mode
- Scroll strategies with intersection-observer triggers

### Background Jobs
- `POST /scrape/fb-posts` returns a `job_id` immediately
- Poll `GET /scrape/fb-posts/status/{job_id}` for live progress (0–100%)
- Max 1 concurrent job — Selenium is resource-heavy
- Job store auto-purges after 20 jobs

### Facebook Auth — 3 Login Methods
| Method | Endpoint | How |
|--------|----------|-----|
| Browser window | `POST /auth/fb-login` | Opens visible Chrome, user logs in manually |
| Cookie paste | `POST /auth/set-cookies` | Paste `document.cookie` from browser console |
| Chrome profile | `GET /auth/fb-cookies-from-profile` | Reads existing logged-in Chrome profile |

- All methods persist cookies to SQLite — survive server restarts
- `GET /auth/fb-status` — check current login state
- `POST /auth/fb-logout` — clear session

---

## Media Proxy

### Stream Proxy
`GET /proxy/media?url=...`
- Streams Facebook CDN media through the server (CORS bypass)
- Attaches saved FB cookies automatically
- Auto-detects content type

### Download with DASH Merge
`GET /proxy-download?url=...&audio_url=...&filename=...`
- Downloads video directly to client
- If `audio_url` provided: merges video + audio using `ffmpeg` (DASH reels)
- Streams merged file without keeping it on disk (cleanup on close)

---

## Data Storage — SQLite

- All scrape sessions and posts stored in `app/scraper.db`
- Tables: `scrape_sessions`, `posts`, `app_settings`
- Posts tagged by `content_type`: `post` or `reel`
- Full-text search on caption
- Filter by page URL, date range, content type
- Paginated with `limit` / `offset`

### API
```
GET    /db/sessions              list all sessions
GET    /db/sessions/{id}         one session + posts
DELETE /db/sessions/{id}
GET    /db/posts                 paginated with filters
DELETE /db/posts/{id}
GET    /db/stats                 totals
GET    /db/export/excel          download .xlsx
```

---

## Excel Export — `/db/export/excel`

- Exports posts or reels to `.xlsx`
- Columns: #, Image (embedded, 160×160px), Caption, Date, Post URL
- Images fetched + resized + padded via Pillow
- Hyperlinked post URLs
- Frozen header row, auto-filter
- Streams directly — no temp file on disk
- Supports `post_ids` param for selected-post export

---

## Profile Scraper — `/scrape/profile`

| Platform | Method |
|----------|--------|
| Instagram | API (no browser) |
| Twitter / X | API (no browser) |
| Facebook | Selenium |
| Reddit | Selenium |
| GitHub | Selenium |
| TikTok | Selenium |
| Pinterest | Selenium |

---

## Retry System — `core/retry/policy.py`

- Configurable max attempts, base delay, backoff multiplier, jitter
- Three presets: `DEFAULT_RETRY`, `AGGRESSIVE_RETRY`, `NO_RETRY`
- Any module can use it independently

---

## Cache — `core/cache/memory_cache.py`

- Thread-safe in-memory TTL cache
- Future: swap with Redis without changing callers

---

## Renderer — `core/renderer/playwright_renderer.py`

- Playwright headless Chromium renderer
- Accepts cookies, custom user agent, wait time
- Used for JS-heavy pages where plain httpx is insufficient


---

## 🎯 AI Extraction Layer (Ready for Integration)

### Text Analyzer — `core/ai/text_analyzer.py`
Placeholder ready for:
- Text summarization
- Keyword extraction
- Named entity recognition (NER)
- Language detection
- Sentiment analysis
- Content classification

**Future integrations:**
- OpenAI GPT-4
- Anthropic Claude
- Local models (LLaMA, Mistral)

**Current state:** Returns structured placeholders. Add API key to enable.
