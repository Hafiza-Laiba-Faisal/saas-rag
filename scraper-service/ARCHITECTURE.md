# Architecture

## Design Principles

- **Single Responsibility** — every module does one thing
- **Interface-first** — all core modules have a `base.py` interface; callers depend on the interface, not the implementation
- **Dependency Injection** — services accept their dependencies; no hard-coded singletons in business logic
- **No circular imports** — routes → services → core; never the reverse
- **Pluggable** — swap any implementation (fetcher, storage, cache, renderer) without touching routes
- **Incrementally refactored** — existing `database.py`, `fb_auth.py`, `fb_posts_scraper.py` are preserved and wrapped, not rewritten

---

## Module Map

```
app/
│
├── api/routes/          HTTP layer only — no business logic
│   ├── auth.py          /auth/*
│   ├── scrape.py        /scrape/*
│   ├── storage.py       /db/*
│   ├── proxy.py         /proxy/*, /proxy-download
│   └── crawl.py         /crawl
│
├── core/                Framework-independent building blocks
│   ├── fetcher/         HTTP requests only
│   │   ├── base.py      BaseFetcher interface
│   │   └── httpx_fetcher.py   Default implementation
│   │
│   ├── renderer/        JavaScript rendering only
│   │   ├── base.py      BaseRenderer interface
│   │   └── playwright_renderer.py
│   │
│   ├── parser/          HTML → parse tree only
│   │   ├── base.py      BaseParser interface
│   │   └── bs4_parser.py
│   │
│   ├── extractor/       parse tree → structured data
│   │   ├── base.py      ContentExtractor, MetadataExtractor, LinksExtractor, AssetsExtractor
│   │   ├── metadata_extractor.py
│   │   └── links_extractor.py
│   │
│   ├── formatter/       data → output format
│   │   ├── base.py      BaseFormatter interface
│   │   └── markdown_formatter.py   JSON + Markdown
│   │
│   ├── detectors/       page condition detection (never bypass)
│   │   ├── base.py      BaseDetector interface
│   │   └── login_detector.py   Login, Cloudflare, Captcha, JS-required
│   │
│   ├── cache/           abstract cache
│   │   ├── base.py      BaseCache interface
│   │   └── memory_cache.py    In-memory TTL (future: Redis)
│   │
│   └── retry/           retry strategy
│       └── policy.py    RetryPolicy with exponential backoff + jitter
│
├── storage/             data persistence
│   ├── base.py          BaseStorage interface
│   └── sqlite_storage.py      SQLite adapter (future: Postgres, S3)
│
├── session/             browser session management
│   └── browser_session.py     Facade over fb_auth.py
│
├── cookies/             cookie import/export
│   └── cookie_store.py  Parse, persist, export cookie sets
│
├── jobs/                background job registry
│   └── job_store.py     Thread-safe in-memory store (future: Celery/ARQ)
│
├── schemas/             Pydantic v2 models
│   ├── base.py          ApiResponse[T] envelope + Metrics + ErrorDetail
│   └── scraper.py       FB request/response models
│
├── config/
│   └── settings.py      All config in one place — loaded once at startup
│
└── utils/
    └── media.py         Image resize, content-type detection
```

---

## Crawl Pipeline

```
Client Request
     │
     ▼
POST /crawl  or  GET /crawl/test
     │
     ▼
Validate URL (must be http/https)
     │
     ▼
HttpxFetcher.get(url)
  ├── follow redirects
  ├── timeout handling
  └── returns FetchResult {status, content, headers, elapsed_ms}
     │
     ▼
Run Detectors (parallel-friendly, each independent)
  ├── LoginRequiredDetector
  ├── CloudflareDetector
  ├── CaptchaDetector
  └── JavaScriptRequiredDetector
     │
     ▼
BS4Parser.parse(html)
  └── returns BeautifulSoup tree
     │
     ▼
Extractors (operate on parse tree, never on raw HTML)
  ├── DefaultMetadataExtractor  →  {title, og_*, canonical}
  └── DefaultLinksExtractor     →  [{url, text, domain, is_pdf}]
     │
     ▼
Formatter (optional)
  ├── JsonFormatter   →  JSON string
  └── MarkdownFormatter → Markdown string
     │
     ▼
ApiResponse.ok(data, metrics)
  └── {success, data, errors[], metrics{fetch_ms, parse_ms, extract_ms}}
```

---

## Facebook Scrape Pipeline

```
POST /scrape/fb-posts
     │
     ▼
FbScrapeRequest validation (Pydantic — URL normalised in validator)
     │
     ▼
Resolve cookies (request → saved session → empty)
     │
     ▼
JobStore.create()  →  ScrapeJob{job_id, status: pending}
     │
     ▼
Return {job_id} immediately
     │
     ▼  (background thread)
scrape_facebook_posts(...)
  ├── init_driver()       headless Chrome, anti-detection flags
  ├── inject_cookies()    FB session cookies
  ├── navigate to page
  ├── extract_from_source()
  │     ├── parse script JSON blobs
  │     ├── _walk() recursive tree
  │     └── _extract_post_node() / _extract_media_from_attachment()
  ├── extract_from_dom()  JS fallback
  ├── scroll N rounds
  ├── _extract_dash_from_source()   DASH manifest parse
  ├── get_page_meta()
  └── classify posts vs reels
     │
     ▼
SQLiteStorage.save_session()
     │
     ▼
job.status = "done", job.result = {...}
     │
     ▼
GET /scrape/fb-posts/status/{job_id}
  └── returns full result when done
```

---

## Dependency Flow (no circular imports)

```
routes
  └── session, storage, jobs, schemas, config, utils
        └── core (fetcher, parser, extractor, formatter, detectors, cache, retry)
              └── config/settings  (leaf — no app imports)
```

Routes never import from routes. Core never imports from routes or services.

---

## SQLite Schema

```sql
scrape_sessions
  id           INTEGER PK AUTOINCREMENT
  page_url     TEXT NOT NULL
  page_title   TEXT
  page_image   TEXT
  page_desc    TEXT
  page_meta    TEXT          -- JSON blob
  scraped_at   TEXT
  posts_count  INTEGER DEFAULT 0
  reels_count  INTEGER DEFAULT 0

posts
  id           INTEGER PK AUTOINCREMENT
  session_id   INTEGER → scrape_sessions.id  ON DELETE CASCADE
  post_id      TEXT
  content_type TEXT          -- 'post' | 'reel'
  caption      TEXT
  media        TEXT          -- JSON array [{type, url, thumb, audio_url}]
  likes        INTEGER DEFAULT 0
  comments     INTEGER DEFAULT 0
  shares       INTEGER DEFAULT 0
  posted_at    TEXT
  post_url     TEXT
  saved_at     TEXT

app_settings
  key          TEXT PK
  value        TEXT
  updated_at   TEXT          -- used for cookie persistence
```

---

## Interface Contract Examples

### Swap fetcher (httpx → requests)
```python
# New implementation
class RequestsFetcher(BaseFetcher):
    def fetch(self, url, method="GET", headers=None, timeout=30, **kwargs):
        ...

# In crawl.py — zero changes to callers
_fetcher = RequestsFetcher()
```

### Swap storage (SQLite → PostgreSQL)
```python
class PostgresStorage(BaseStorage):
    def save_session(self, ...): ...
    def get_all_posts(self, ...): ...
    ...

# In routes/storage.py
from storage.postgres_storage import PostgresStorage
default_storage = PostgresStorage()
```

### Swap cache (memory → Redis)
```python
class RedisCache(BaseCache):
    def get(self, key): ...
    def set(self, key, value, ttl_seconds=300): ...
    ...
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI |
| ASGI Server | Uvicorn |
| Data Validation | Pydantic v2 |
| HTTP Fetcher | httpx |
| JS Renderer | Playwright |
| Browser Automation | Selenium 4 |
| HTML Parser | BeautifulSoup4 |
| Cloudflare Bypass | cloudscraper (available) |
| Database | SQLite (built-in) |
| Excel Export | openpyxl + Pillow |
| Video Merge | ffmpeg (system) |
| Python | 3.11+ |

---

## Future Extension Points

| Feature | Where to add |
|---------|-------------|
| Redis cache | `core/cache/redis_cache.py` implementing `BaseCache` |
| PostgreSQL | `storage/postgres_storage.py` implementing `BaseStorage` |
| Celery/ARQ jobs | Replace `jobs/job_store.py` implementation |
| Proxy providers | New param in `BaseFetcher.fetch()` |
| Browser pool | Extend `core/renderer/` |
| Rate limiting | Middleware in `main.py` |
| OCR extractor | `core/extractor/ocr_extractor.py` |
| AI extraction | `core/extractor/ai_extractor.py` |
| CLI | `cli/` folder using `typer` |
| MCP Server | `mcp/` folder exposing crawl tools |
| SDK | `sdk/` folder wrapping API client |
| Recursive crawl | `core/crawler/` with scheduler + robots.txt |
