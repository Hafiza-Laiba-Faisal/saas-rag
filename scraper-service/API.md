# Scraper Service — API Reference

Base URL: `http://localhost:8000`  
Auto-docs: `http://localhost:8000/docs` (Swagger UI)

---

## Response Envelope

All endpoints return `ApiResponse` except `GET /` and `GET /platforms`.

```json
{
  "success": true,
  "data": { ... },
  "errors": [
    { "stage": "fetcher", "reason": "request_failed", "detail": "..." }
  ],
  "metrics": {
    "fetch_time_ms": 0.0,
    "parse_time_ms": 0.0,
    "extract_time_ms": 0.0,
    "rendered": false
  }
}
```

---

## 1. Info

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service name, version, quick endpoint summary |
| `GET` | `/platforms` | Supported social platforms with `requires_browser` flag |

**Platforms:** instagram, twitter, facebook, reddit, github, tiktok, pinterest

---

## 2. Auth (`/auth`)

| Method | Path | Request | Response | Description |
|--------|------|---------|----------|-------------|
| `POST` | `/auth/set-cookies` | `{"cookies": "c_user=...; xs=..."}` | `{"message", "c_user"}` | Parse raw `document.cookie` and store Facebook session |
| `POST` | `/auth/fb-login` | query: `timeout=300` | Browser login result | Start browser-based Facebook login (QR/manual) |
| `GET` | `/auth/fb-status` | — | Login status | Check current Facebook auth state |
| `POST` | `/auth/fb-cancel` | — | Cancel result | Cancel pending login |
| `POST` | `/auth/fb-logout` | — | Logout result | Clear Facebook session |
| `GET` | `/auth/fb-cookies-from-profile` | query: `profile=Default` | `{"cookies": ...}` | Extract cookies from local Chrome profile |

---

## 3. Scrape (`/scrape`)

### `POST /scrape/fb-posts`
Scrape Facebook page posts/reels as a **background job**.

```json
{
  "page_url": "https://www.facebook.com/SomePage",
  "c_user": "",
  "xs": "",
  "datr": "",
  "sb": "",
  "fr": "",
  "browser": "chrome",
  "max_posts": 20,
  "scroll_rounds": 5,
  "date_from": "",
  "date_to": ""
}
```

Returns: `{"job_id": "...", "status": "pending", "message": "..."}`

### `GET /scrape/fb-posts/status/{job_id}`
Poll background job progress.

Returns: `{"job_id", "job_type", "status", "progress", "message", "result", "error", "metadata", "created_at"}`

When `status == "done"`, `result` contains full `FbScrapeResult` (page_meta, posts, reels, session_id, saved).

### `POST /scrape/profile`
Multi-platform social profile scraper (synchronous).

```json
{
  "platform": "instagram",
  "username": "example",
  "browser": "chrome",
  "proxy": null
}
```

Returns: `{"platform", "username", "data": {...}}` (platform-specific)

### `POST /scrape/wordpress`
Detect & scrape WordPress site via REST API (fallback to HTML).

```json
{
  "url": "https://example.com",
  "max_pages": 10,
  "include_pages": true,
  "include_media": true
}
```

Returns `ApiResponse` with:
- `url`, `is_wordpress`, `detected_by` — detection info
- `posts`, `pages` — scraped content
- `media` — media library items
- `stats` — counts by type
- `error`, `elapsed_ms`

---

## 4. Storage / Database (`/db`)

| Method | Path | Query Params | Description |
|--------|------|--------------|-------------|
| `GET` | `/db/sessions` | — | List all saved scrape sessions |
| `GET` | `/db/sessions/{session_id}` | — | Get single session details |
| `DELETE` | `/db/sessions/{session_id}` | — | Delete a session |
| `GET` | `/db/posts` | `search`, `page_url`, `content_type`, `date_from`, `date_to`, `limit` (1–200), `offset` (≥0) | Query scraped posts with filters |
| `DELETE` | `/db/posts/{post_db_id}` | — | Delete a post by DB ID |
| `GET` | `/db/stats` | — | Storage statistics (total posts, sessions, etc.) |
| `GET` | `/db/export/excel` | `page_url`, `content_type` ("post"/"reel"), `date_from`, `date_to`, `post_ids` (comma-sep), `limit` (1–2000) | Download `.xlsx` export with embedded thumbnails |

---

## 5. Proxy (`/proxy`)

| Method | Path | Query Params | Description |
|--------|------|--------------|-------------|
| `GET` | `/proxy/media` | `url` (required) | Stream remote media (Facebook CDN proxy with auth cookies) |
| `GET` | `/proxy-download` | `url` (required), `audio_url`, `filename` | Download `.mp4` video; if `audio_url` provided, merges DASH audio/video via ffmpeg |

---

## 6. Crawl (`/crawl`)

### `POST /crawl`
Full single-page pipeline: fetch → detect (login/Cloudflare/captcha/JS) → parse (BS4) → extract (metadata + links) → format.

```json
{
  "url": "https://example.com",
  "format": "json"
}
```

`format`: `"json"` | `"markdown"`  

Returns in `data`: `url`, `status`, `title`, `description`, `og_image`, `metadata`, `links` (first 50), `link_count`, `detectors`, `html_length`, `json`/`markdown`.

### `GET /crawl/test`
Same as `POST /crawl` but via GET for easy browser/Swagger testing.  
Params: `url` (default `https://www.nasa.gov/`), `format` (default `json`).

### `POST /crawl/smart`
Smart crawl via `ScraperEngine`: native adapter → quality scoring (0–100) → optional DeepCrawl fallback.

```json
{
  "url": "https://example.com",
  "timeout": 30
}
```

Returns in `data`: `url`, `status_code`, `title`, `description`, `html_length`, `links_count`, `content_type`, `metadata`, `links` (first 50), `detectors`, `quality_score`, `quality_level` ("high"/"medium"/"low"), `adapter_used` ("native"/"deepcrawl"), `error`, `elapsed_ms`, `timing`.

### `POST /crawl/recursive`
Start a **background** full-site recursive crawl.

```json
{
  "url": "https://example.com",
  "max_depth": 3,
  "max_pages": 100,
  "allowed_domains": null,
  "blocked_domains": null,
  "respect_robots": true,
  "timeout": 30,
  "follow_external": false,
  "workers": 1
}
```

Returns: `{"job_id", "status", "message", "poll_url"}`

### `GET /crawl/recursive/status/{job_id}`
Poll recursive crawl job status.

When `status == "completed"`, `result` contains:
- `pages`: `[{url, status, content_type, title, depth, links_found, error, elapsed_ms, timing, readability, assets, metadata}]`
- `stats`: `{total_pages, successful, failed, html_pages, pdf_files, images, other_files, total_time_sec, pages_per_second}`
- `queue_stats`

### `GET /crawl/recursive/jobs`
List all recursive crawl jobs.

### `DELETE /crawl/recursive/{job_id}`
Delete a recursive crawl job.

---

## Request Schema Reference

### `FbScrapeRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `page_url` | `str` | *required* | Facebook page URL (auto-normalised) |
| `c_user` | `str` | `""` | Facebook cookie |
| `xs` | `str` | `""` | Facebook cookie |
| `datr` | `str` | `""` | Facebook cookie |
| `sb` | `str` | `""` | Facebook cookie |
| `fr` | `str` | `""` | Facebook cookie |
| `browser` | `str` | `"chrome"` | Browser engine |
| `max_posts` | `int` | `20` | Max posts (0 = unlimited) |
| `scroll_rounds` | `int` | `5` | Infinite scroll rounds |
| `date_from` | `str` | `""` | Filter YYYY-MM-DD |
| `date_to` | `str` | `""` | Filter YYYY-MM-DD |

### `ProfileScrapeRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `platform` | `str` | *required* | One of: instagram, twitter, facebook, reddit, github, tiktok, pinterest |
| `username` | `str` | *required* | Username (leading `@` stripped) |
| `browser` | `Optional[str]` | `"chrome"` | For selenium-based platforms |
| `proxy` | `Optional[str]` | `null` | Proxy URL |

### `WordPressScrapeRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `str` | *required* | WordPress site URL |
| `max_pages` | `int` | `10` | Max pages/posts to scrape |
| `include_pages` | `bool` | `true` | Include WP pages |
| `include_media` | `bool` | `true` | Include media items |

### `RecursiveCrawlRequest`
| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `url` | `str` | *required* | — | Seed URL |
| `max_depth` | `int` | `3` | 1–10 | Max crawl depth |
| `max_pages` | `int` | `100` | 1–10000 | Max pages to crawl |
| `allowed_domains` | `list[str] \| null` | `null` | — | Domain whitelist (null = seed domain only) |
| `blocked_domains` | `list[str] \| null` | `null` | — | Domain blacklist |
| `respect_robots` | `bool` | `true` | — | Honor `robots.txt` |
| `timeout` | `int` | `30` | 5–120 | Request timeout (seconds) |
| `follow_external` | `bool` | `false` | — | Follow external domain links |
| `workers` | `int` | `1` | 1–20 | Concurrent workers |

---

## Quick Start

```bash
# Start server
cd app
../venv/bin/uvicorn main:app --reload --port 8000

# Test crawl
curl http://localhost:8000/crawl/test?url=https://example.com

# Scrape WordPress
curl -X POST http://localhost:8000/scrape/wordpress \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 10}'

# Start recursive crawl
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_depth": 2, "max_pages": 50}'

# Query stored posts
curl "http://localhost:8000/db/posts?limit=10&content_type=post"

# Export to Excel
curl "http://localhost:8000/db/export/excel?content_type=post&limit=100" -o posts.xlsx
```
