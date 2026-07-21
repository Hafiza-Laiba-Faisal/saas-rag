"""
Scrape routes — WordPress scraper only.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from schemas.base import ApiResponse
from scrapers.wordpress_scraper import WordPressScraper

router = APIRouter(prefix="/scrape", tags=["scrape"])

logger = logging.getLogger(__name__)

_wp_scraper = WordPressScraper()


class WordPressScrapeRequest(BaseModel):
    url: str
    max_pages: int = 10
    include_pages: bool = True
    include_media: bool = True


@router.post("/wordpress", summary="Scrape WordPress site via REST API")
async def scrape_wordpress(req: WordPressScrapeRequest):
    """
    Detect and scrape a WordPress site.
    Tries WP REST API first (/wp-json/wp/v2/posts), falls back to HTML parsing.
    Returns posts, pages, media, and metadata in one shot.
    """
    url = req.url.strip()
    logger.info("WordPress scrape: url=%s max_pages=%s", url, req.max_pages)
    if not url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url",
                                "URL must start with http:// or https://")
    result = await _wp_scraper.scrape(
        url,
        max_pages=req.max_pages,
        include_pages=req.include_pages,
        include_media=req.include_media,
    )
    return ApiResponse.ok({
        "url": result.url,
        "is_wordpress": result.is_wordpress,
        "detected_by": result.detected_by,
        "posts": result.posts,
        "pages": result.pages,
        "media": result.media,
        "stats": result.stats,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
    })
