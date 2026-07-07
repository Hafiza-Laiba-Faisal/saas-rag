"""
Central configuration — loaded once at startup.
All modules import from here instead of reading env directly.
"""

import os
from pathlib import Path
from typing import Literal

# ── Base paths ────────────────────────────────────────────────────────────────
ROOT_DIR     = Path(__file__).parent.parent.parent   # scraper-service/
APP_DIR      = ROOT_DIR / "app"
DOWNLOADS_DIR = ROOT_DIR / "downloads"
DB_PATH      = APP_DIR / "scraper.db"

# ── Load .env if present ──────────────────────────────────────────────────────
_env_file = ROOT_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ── App settings ──────────────────────────────────────────────────────────────
APP_TITLE   = "Scraper Service"
APP_VERSION = "3.0.0"
DEBUG       = os.getenv("DEBUG", "false").lower() == "true"

# ── Browser settings ──────────────────────────────────────────────────────────
DEFAULT_BROWSER: Literal["chrome", "firefox"] = "chrome"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_WINDOW_SIZE = (1920, 1080)

# ── Scraping settings ─────────────────────────────────────────────────────────
MAX_CONCURRENT_JOBS  = 1      # Selenium is heavy — keep 1
MAX_JOBS_IN_MEMORY   = 20     # auto-purge old jobs
DEFAULT_MAX_POSTS    = 50
DEFAULT_SCROLL_ROUNDS = 5
SCROLL_PAUSE_SECONDS  = 3.0
MAX_SCROLL_ROUNDS_UNLIMITED = 2000

# ── HTTP settings ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT     = 60
STREAM_CHUNK_SIZE   = 65536
MAX_CONNECTIONS     = 200
MAX_KEEPALIVE_CONNECTIONS = 50
MAX_DOWNLOAD_SIZE   = 100 * 1024 * 1024

# ── Excel export ──────────────────────────────────────────────────────────────
EXCEL_IMG_WIDTH  = 160
EXCEL_IMG_HEIGHT = 160
EXCEL_ROW_HEIGHT = 130
EXCEL_HEADER_COLOR = "1877F2"

# ── Facebook ──────────────────────────────────────────────────────────────────
FB_BASE_URL = "https://www.facebook.com"
FB_ALLOWED_CDN_DOMAINS = ("fbcdn.net", "facebook.com", "fbsbx.com", "cdninstagram.com")
FB_LOGIN_TIMEOUT_SECONDS = 900

# ── Allowed proxy domains (media proxy endpoint) ──────────────────────────────
PROXY_ALLOWED_DOMAINS = FB_ALLOWED_CDN_DOMAINS
