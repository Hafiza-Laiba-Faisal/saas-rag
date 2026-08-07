"""
Scraper Service — FastAPI entry point
=====================================
Run:
  cd app && ../venv/bin/uvicorn main:app --reload --port 8000
"""

import sys, os, logging, tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler
_root = os.path.dirname(os.path.dirname(__file__))
_app  = os.path.dirname(__file__)
for _p in (_root, _app):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx

from config.settings import APP_TITLE, APP_VERSION, MAX_CONNECTIONS, MAX_KEEPALIVE_CONNECTIONS
from core.fetcher import client as global_client
from api.routes import scrape, crawl, recursive, full_crawl, logs as logs_router
from core.logs import in_memory_handler

def build_logging_handlers(log_file: str | None = None) -> list[logging.Handler]:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    candidate = log_file or os.environ.get("SCRAPER_LOG_FILE") or os.path.join(_root, ".logs", "scraper.log")
    fallback = Path(tempfile.gettempdir()) / "scraper.log"
    last_error: Exception | None = None

    for path in (Path(candidate).expanduser(), fallback):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not os.access(path.parent, os.W_OK):
                raise PermissionError(f"{path.parent} is not writable")
            path.touch(exist_ok=True)
            if not os.access(path, os.W_OK):
                raise PermissionError(f"{path} is not writable")
            handlers.append(RotatingFileHandler(str(path), maxBytes=5 * 1024 * 1024, backupCount=3))
            return handlers + [in_memory_handler]
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = exc

    logging.getLogger(__name__).warning(
        "Falling back to stream logging because the file logger could not be created: %s",
        last_error,
    )
    return handlers + [in_memory_handler]


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=build_logging_handlers(),
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS)
    global_client.async_client = httpx.AsyncClient(http2=False, limits=limits, follow_redirects=True)
    yield
    if global_client.async_client:
        await global_client.async_client.aclose()

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description="Web scraping platform — general web crawler, smart crawl, recursive crawl, and WordPress scraper.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrape.router)
app.include_router(crawl.router)
app.include_router(recursive.router)
app.include_router(full_crawl.router)
app.include_router(logs_router.router)


@app.get("/", tags=["info"])
def root():
    return {
        "service":  APP_TITLE,
        "version":  APP_VERSION,
        "docs":     "/docs",
        "endpoints": {
            "crawl":            "POST /crawl  |  GET /crawl/test?url=...",
            "smart_crawl":      "POST /crawl/smart (quality scoring + fallback)",
            "recursive_crawl":  "POST /crawl/recursive",
            "full_site_crawl":  "POST /crawl/full (unified: text + images + PDFs)",
            "wp_scrape":        "POST /scrape/wordpress",
        },
    }
