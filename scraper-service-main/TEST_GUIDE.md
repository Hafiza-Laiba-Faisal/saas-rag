# Testing Guide

## Quick Start

### 1. Start Server
```bash
cd app
../venv/bin/uvicorn main:app --reload --port 8000
```

Server: `http://localhost:8000`  
Swagger: `http://localhost:8000/docs`

---

## Test Cases

### ✅ Test 1: Single Page Crawl
```bash
# Quick test
curl "http://localhost:8000/crawl/test?url=https://example.com"

# Full request
curl -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "format": "json"}'
```

**Expected result:**
- Status 200
- `success: true`
- Extracted metadata (title, description, og tags)
- Links found
- Metrics (fetch_time_ms, parse_time_ms)

---

### ✅ Test 2: Recursive Crawler
```bash
# Start crawl
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_depth": 2,
    "max_pages": 20,
    "respect_robots": true,
    "timeout": 30
  }'

# Response: {"success": true, "data": {"job_id": "abc123", ...}}

# Check progress (repeat until status: completed)
curl http://localhost:8000/crawl/recursive/status/abc123

# List all jobs
curl http://localhost:8000/crawl/recursive/jobs
```

**Expected result:**
- Job created immediately
- Progress updates (0% → 100%)
- Final result with:
  - List of pages crawled
  - Stats (total, successful, failed)
  - Content type distribution
  - Pages per second

---

### ✅ Test 3: URL Normalization
Test that these URLs are treated as same:
```bash
# All should deduplicate to same URL
curl http://localhost:8000/crawl/recursive \
  -d '{"url": "https://example.com/page", "max_pages": 5}'

# Should not re-crawl:
# - https://example.com/page/
# - https://example.com/page#section
# - https://example.com/page?utm_source=test
```

---

### ✅ Test 4: Domain Filtering
```bash
# Whitelist: Only crawl example.com
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "allowed_domains": ["example.com"],
    "max_pages": 50
  }'

# Blacklist: Skip subdomain
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "blocked_domains": ["blog.example.com"],
    "max_pages": 50
  }'
```

---

### ✅ Test 5: robots.txt Compliance
```bash
# Test with site that has robots.txt
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://github.com",
    "max_pages": 10,
    "respect_robots": true
  }'

# Check that disallowed paths are skipped
```

---

### ✅ Test 6: Content Type Detection
```bash
# Site with mixed content (HTML, PDF, images)
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.w3.org/",
    "max_pages": 30
  }'

# Check result stats:
# - html_pages count
# - pdf_files count
# - images count
```

---

### ✅ Test 7: Depth Control
```bash
# Crawl only 1 level deep
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_depth": 1,
    "max_pages": 100
  }'

# Verify in results that depth never exceeds 1
```

---

### ✅ Test 8: Error Handling
```bash
# Invalid URL
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{"url": "not-a-url"}'

# Timeout
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://httpstat.us/200?sleep=60000",
    "timeout": 5,
    "max_pages": 1
  }'

# 404 page
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/this-does-not-exist",
    "max_pages": 1
  }'
```

**Expected:**
- Graceful error messages
- No server crashes
- Failed pages tracked in stats

---

### ✅ Test 9: Concurrent Jobs
```bash
# Start multiple crawls simultaneously
for i in {1..3}; do
  curl -X POST http://localhost:8000/crawl/recursive \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"https://example.com/page$i\", \"max_pages\": 10}" &
done

# Check all jobs running
curl http://localhost:8000/crawl/recursive/jobs
```

**Expected:**
- All jobs accepted
- Run in background
- No race conditions

---

### ✅ Test 10: Job Cleanup
```bash
# Create 60 jobs (exceeds max of 50)
for i in {1..60}; do
  curl -X POST http://localhost:8000/crawl/recursive \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"https://example.com\", \"max_pages\": 5}" > /dev/null 2>&1
  sleep 0.5
done

# Check jobs list (should auto-purge oldest)
curl http://localhost:8000/crawl/recursive/jobs
```

**Expected:**
- Only last 50 jobs retained
- Oldest jobs auto-deleted

---

## Performance Benchmarks

### Small Site (10 pages)
```bash
time curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 10}'
```

**Target:**
- < 30 seconds total
- > 0.3 pages/sec

### Medium Site (100 pages)
```bash
curl -X POST http://localhost:8000/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 100, "max_depth": 5}'
```

**Target:**
- < 3 minutes total
- > 0.5 pages/sec

---

## Facebook Scraper Tests

### Test 11: FB Login
```bash
# Method 1: Browser login
curl -X POST http://localhost:8000/auth/fb-login

# Method 2: Cookie paste
curl -X POST http://localhost:8000/auth/set-cookies \
  -H "Content-Type: application/json" \
  -d '{"cookies": "your_cookie_string_here"}'

# Check status
curl http://localhost:8000/auth/fb-status
```

---

### Test 12: FB Posts Scraper
```bash
# Start scrape
curl -X POST http://localhost:8000/scrape/fb-posts \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.facebook.com/nasa",
    "max_posts": 20,
    "scroll_rounds": 5
  }'

# Poll status
curl http://localhost:8000/scrape/fb-posts/status/{job_id}
```

---

## Validation Checklist

After all tests:

- [ ] No server crashes
- [ ] All errors are structured (never raw exceptions in response)
- [ ] Metrics present in all responses
- [ ] URLs properly deduplicated
- [ ] robots.txt honored
- [ ] Content types correctly detected
- [ ] Progress tracking works (0% → 100%)
- [ ] Jobs auto-cleanup after 50
- [ ] Thread-safe (no race conditions)
- [ ] Memory usage stable (no leaks)

---

## Expected Issues (Known Limitations)

1. **No rate limiting** — may get IP banned on aggressive crawls
2. **Single-instance only** — no distributed crawling yet
3. **No proxy rotation** — uses same IP for all requests
4. **In-memory queue** — lost on server restart
5. **No retry on transient failures** — 503/504 not auto-retried

**These are on roadmap for v2.1+**

---

## Success Criteria

✅ **Crawler is production-ready if:**
1. All 12 tests pass
2. No server crashes
3. Errors are graceful
4. Stats are accurate
5. Deduplication works
6. robots.txt honored
7. Progress tracking real-time
8. Multiple jobs run concurrently
9. Memory usage stable

---

## Report Issues

If any test fails, check:
1. Server logs — `app/logs/` (if enabled)
2. Response errors — look at `errors[]` array
3. Job status — check `status` and `error` fields

**Known working sites for testing:**
- `https://example.com` — simple, fast
- `https://www.w3.org/` — mixed content (HTML, PDF)
- `https://github.com` — large site with robots.txt
- `https://httpbin.org/` — testing endpoints

**Avoid for testing:**
- Sites with aggressive bot protection (Cloudflare challenges)
- Sites requiring login (unless testing FB scraper)
- Rate-limited APIs
