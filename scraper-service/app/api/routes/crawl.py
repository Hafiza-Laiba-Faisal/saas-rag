"""
Crawl route — full pipeline test endpoint.
Client → Validate → Fetcher → Detectors → Parser → Extractor → Formatter → Response
"""
from __future__ import annotations
import time
import threading
from fastapi import APIRouter, Query, BackgroundTasks
from pydantic import BaseModel
from core.fetcher.async_httpx_fetcher import AsyncHttpxFetcher
from core.fetcher.escalating_fetcher import EscalatingFetcher
from core.parser.bs4_parser import BS4Parser
from core.extractor.metadata_extractor import DefaultMetadataExtractor
from core.extractor.links_extractor import DefaultLinksExtractor
from core.detectors.login_detector import (
    LoginRequiredDetector, CloudflareDetector,
    CaptchaDetector, JavaScriptRequiredDetector,
)
from core.formatter.markdown_formatter import MarkdownFormatter, JsonFormatter
from core.crawler.recursive_crawler import RecursiveCrawler, CrawlResult, CrawlStats
from jobs.job_store import JobStore
from schemas.base import ApiResponse, Metrics

router = APIRouter(prefix="/crawl", tags=["crawl"])

# Job store for recursive crawls
_crawl_jobs = JobStore(max_jobs=20)

# Singletons — created once, reused
_fetcher     = EscalatingFetcher()
_parser      = BS4Parser()
_meta_ext    = DefaultMetadataExtractor()
_links_ext   = DefaultLinksExtractor()
_md_fmt      = MarkdownFormatter()
_json_fmt    = JsonFormatter()
_detectors   = [
    LoginRequiredDetector(),
    CloudflareDetector(),
    CaptchaDetector(),
    JavaScriptRequiredDetector(),
]


class CrawlRequest(BaseModel):
    url:    str
    format: str = "json"   # json | markdown


@router.post("")
async def crawl(req: CrawlRequest):
    """
    Full pipeline:
    1. Fetch URL
    2. Run all detectors
    3. Parse HTML (BS4)
    4. Extract metadata + links
    5. Format output
    6. Return consistent ApiResponse envelope
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url",
                                "URL must start with http:// or https://")

    metrics = Metrics()

    # ── Stage 1: Fetch ────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        result = await _fetcher.get(url, timeout=30)
    except Exception as e:
        return ApiResponse.fail("fetcher", "request_failed", str(e))
    metrics.fetch_time_ms = round((time.monotonic() - t0) * 1000, 2)

    if not result.ok:
        return ApiResponse.fail("fetcher", f"http_{result.status_code}",
                                f"Server returned {result.status_code}")

    html = result.text

    # ── Stage 2: Detectors ────────────────────────────────────────────────────
    detected = {}
    for detector in _detectors:
        detected[detector.name] = detector.detect(html, result.final_url or url)

    # ── Stage 3: Parse ────────────────────────────────────────────────────────
    t1 = time.monotonic()
    try:
        tree = _parser.parse(html)
    except Exception as e:
        return ApiResponse.fail("parser", "parse_failed", str(e))
    metrics.parse_time_ms = round((time.monotonic() - t1) * 1000, 2)

    # ── Stage 4: Extract ──────────────────────────────────────────────────────
    t2 = time.monotonic()
    final_url = result.final_url or url
    metadata  = _meta_ext.extract(tree, final_url)
    links     = _links_ext.extract(tree, final_url)
    metrics.extract_time_ms = round((time.monotonic() - t2) * 1000, 2)

    # ── Stage 5: Format ───────────────────────────────────────────────────────
    page_data = {
        "url":        final_url,
        "status":     result.status_code,
        "title":      metadata.get("og_title") or metadata.get("title", ""),
        "description": metadata.get("og_description") or metadata.get("description", ""),
        "og_image":   metadata.get("og_image", ""),
        "metadata":   metadata,
        "links":      links["links"][:50],
        "link_count": links["count"],
        "detectors":  detected,
        "html_length": len(html),
    }

    if req.format == "markdown":
        page_meta   = {"title": page_data["title"], "about": page_data["description"]}
        formatted   = _md_fmt.format_page(page_meta, [])
        page_data["markdown"] = formatted
    else:
        page_data["json"] = _json_fmt.format_page(
            {"title": page_data["title"]}, []
        )

    return ApiResponse.ok(data=page_data, metrics=metrics)


@router.get("/test")
async def crawl_test(
    url:    str = Query(default="https://www.nasa.gov/"),
    format: str = Query(default="json"),
):
    """Quick GET version for browser/Swagger testing."""
    return await crawl(CrawlRequest(url=url, format=format))


# ── Smart Crawl (ScraperEngine with fallback) ─────────────────────────────────

from core.engine import ScraperEngine

_engine = ScraperEngine(fallback_threshold=0.4)


class SmartCrawlRequest(BaseModel):
    url: str
    timeout: int = 30


@router.post("/smart", summary="Smart crawl with quality scoring and fallback")
async def smart_crawl(req: SmartCrawlRequest):
    """
    Smart single-page crawl using ScraperEngine.
    
    - Tries native adapter first
    - Scores extraction quality (0-100)
    - Falls back to DeepCrawl if quality is low and adapter is configured
    - Returns quality score, timing breakdown, and adapter used
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url", "URL must start with http:// or https://")

    result = await _engine.scrape(url, timeout=req.timeout)

    return ApiResponse.ok({
        "url": result.url,
        "status_code": result.status_code,
        "title": result.title,
        "description": result.description,
        "html_length": result.html_length,
        "links_count": result.links_count,
        "content_type": result.content_type,
        "metadata": result.metadata,
        "links": result.links[:50],
        "detectors": result.detectors,
        "quality_score": result.quality_score,
        "quality_level": result.quality_level,
        "adapter_used": result.adapter_used,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
        "timing": result.timing,
    })

