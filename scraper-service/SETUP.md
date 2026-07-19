# Setup Guide

## Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| Google Chrome | Any recent | Selenium + Playwright |
| ffmpeg | Any | DASH video+audio merge (optional) |

---

## Step 1 — Virtual Environment

```bash
cd scraper-service
python3 -m venv venv
```

---

## Step 2 — Install Dependencies

```bash
venv/bin/pip install -r requirements.txt --only-binary=:all:
```

> `--only-binary=:all:` is required on Python 3.13+ to avoid build failures on `greenlet` and `pydantic-core`.

---

## Step 3 — Install Chromium

```bash
venv/bin/playwright install chromium
```

---

## Step 4 — Environment Variables

```bash
cp .env.example .env
# No API keys required for basic scraping
```

---

## Step 5 — Run the Server

```bash
cd app
PYTHONPATH=.. ../venv/bin/uvicorn main:app --reload --port 8000
```

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

For production:

```bash
cd app
PYTHONPATH=.. ../venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

> Use `--workers 1` — Selenium jobs are thread-based and don't share state across processes.

---

## Run as Background Service (Linux)

```bash
cd app
nohup bash -c 'PYTHONPATH=.. ../venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000' \
  > ../scraper.log 2>&1 &
echo $! > ../scraper.pid

# Stop
kill $(cat ../scraper.pid)
```

---

## Facebook Login — 3 Options

### Option A — Browser Window (Recommended)
```bash
# Opens a visible Chrome window — log in manually
POST http://localhost:8000/auth/fb-login

# Poll until done
GET http://localhost:8000/auth/fb-status
```

### Option B — Paste Cookies
1. Open Facebook in your browser and log in
2. Open DevTools → Console
3. Run: `document.cookie`
4. Copy the full string, send to API:

```bash
POST http://localhost:8000/auth/set-cookies
Content-Type: application/json

{"cookies": "c_user=123456; xs=abc123; datr=xyz; sb=..."}
```

### Option C — Chrome Profile
```bash
# Close Chrome first, then:
GET http://localhost:8000/auth/fb-cookies-from-profile?profile=Default
```

---

## ffmpeg (for Reel Downloads)

Required only for downloading reels with audio:

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

---

## Project Structure

```
scraper-service/
├── app/
│   ├── main.py                        ← FastAPI entry point
│   ├── database.py                    ← SQLite operations
│   ├── fb_auth.py                     ← Facebook auth
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py                ← /auth/* endpoints
│   │       ├── scrape.py              ← /scrape/* endpoints
│   │       ├── storage.py             ← /db/* endpoints
│   │       ├── proxy.py               ← /proxy/* endpoints
│   │       └── crawl.py               ← /crawl endpoints
│   ├── core/
│   │   ├── fetcher/                   ← HTTP request layer
│   │   ├── renderer/                  ← Playwright JS renderer
│   │   ├── parser/                    ← HTML → parse tree
│   │   ├── extractor/                 ← parse tree → structured data
│   │   ├── formatter/                 ← data → JSON / Markdown
│   │   ├── detectors/                 ← page condition detection
│   │   ├── cache/                     ← in-memory TTL cache
│   │   └── retry/                     ← retry policy engine
│   ├── config/
│   │   └── settings.py                ← all config in one place
│   ├── schemas/
│   │   ├── base.py                    ← ApiResponse envelope
│   │   └── scraper.py                 ← request/response models
│   ├── storage/
│   │   ├── base.py                    ← storage interface
│   │   └── sqlite_storage.py          ← SQLite implementation
│   ├── session/
│   │   └── browser_session.py         ← auth service facade
│   ├── cookies/
│   │   └── cookie_store.py            ← cookie persistence
│   ├── jobs/
│   │   └── job_store.py               ← background job registry
│   ├── scrapers/
│   │   └── fb_posts_scraper.py        ← Selenium scraper engine
│   └── utils/
│       └── media.py                   ← image resize, content-type
├── downloads/
├── venv/
├── .env.example
├── requirements.txt
├── README.md
├── FEATURES.md
├── SETUP.md
└── ARCHITECTURE.md
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'app'` | Set `PYTHONPATH=..` when running from `app/` |
| `greenlet` or `pydantic-core` build fails | Use `--only-binary=:all:` |
| Port already in use | `fuser -k 8000/tcp` then retry |
| Chrome not found | `venv/bin/playwright install chromium` |
| FB login timeout | `POST /auth/fb-login?timeout=600` |
| Chrome profile in use | Close Chrome first |
| No audio on reel download | Install `ffmpeg` |
| `address already in use` | Another server running — use different port |
