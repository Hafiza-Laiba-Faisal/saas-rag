"""
Scraper Service — FastAPI entry point
=====================================
Run:
  cd app && ../venv/bin/uvicorn main:app --reload --port 8000
"""

import sys, os
# Add project root so both `app.X` and direct imports work
_root = os.path.dirname(os.path.dirname(__file__))   # scraper-service/
_app  = os.path.dirname(__file__)                     # scraper-service/app/
for _p in (_root, _app):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx

from config.settings import APP_TITLE, APP_VERSION, MAX_CONNECTIONS, MAX_KEEPALIVE_CONNECTIONS
from core.fetcher import client as global_client
from api.routes import auth, scrape, storage, proxy, crawl, recursive

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
    description="Modular scraping platform — Facebook, social media, general web crawler.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(scrape.router)
app.include_router(storage.router)
app.include_router(proxy.router)
app.include_router(crawl.router)
app.include_router(recursive.router)


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["info"])
def root():
    return {
        "service":  APP_TITLE,
        "version":  APP_VERSION,
        "docs":     "/docs",
        "endpoints": {
            "crawl":           "POST /crawl  |  GET /crawl/test?url=...",
            "smart_crawl":     "POST /crawl/smart (quality scoring + fallback)",
            "recursive_crawl": "POST /crawl/recursive",
            "fb_posts":        "POST /scrape/fb-posts",
            "auth":            "POST /auth/fb-login",
            "db":              "GET /db/posts",
            "proxy":           "GET /proxy/media",
        },
    }


@app.get("/platforms", tags=["info"])
def platforms():
    return {
        "platforms": [
            {"id": "instagram",  "name": "Instagram",   "requires_browser": False},
            {"id": "twitter",    "name": "Twitter / X", "requires_browser": False},
            {"id": "facebook",   "name": "Facebook",    "requires_browser": True},
            {"id": "reddit",     "name": "Reddit",      "requires_browser": True},
            {"id": "github",     "name": "GitHub",      "requires_browser": True},
            {"id": "tiktok",     "name": "TikTok",      "requires_browser": True},
            {"id": "pinterest",  "name": "Pinterest",   "requires_browser": True},
        ]
    }
