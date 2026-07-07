"""
Recursive crawler API — background jobs with full site crawling.
"""
from __future__ import annotations
import threading
from typing import Optional
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from core.crawler.recursive_crawler import RecursiveCrawler, CrawlResult, CrawlStats
from jobs.job_store import JobStore
from schemas.base import ApiResponse

router = APIRouter(prefix="/crawl", tags=["recursive-crawler"])

# Job store
_crawl_jobs = JobStore(max_jobs=50)


class RecursiveCrawlRequest(BaseModel):
    """Request model for recursive crawl."""
    url: str = Field(..., description="Seed URL to start crawling")
    max_depth: int = Field(3, ge=1, le=10, description="Maximum crawl depth")
    max_pages: int = Field(100, ge=1, le=10000, description="Maximum pages to crawl")
    allowed_domains: list[str] | None = Field(None, description="Domain whitelist (None = seed domain only)")
    blocked_domains: list[str] | None = Field(None, description="Domain blacklist")
    respect_robots: bool = Field(True, description="Honor robots.txt")
    timeout: int = Field(30, ge=5, le=120, description="Request timeout in seconds")
    follow_external: bool = Field(False, description="Follow links to external domains")
    workers: int = Field(1, ge=1, le=20, description="Concurrent workers")


async def _execute_recursive_crawl(job_id: str, request: RecursiveCrawlRequest):
    """Background task to execute recursive crawl."""
    job = _crawl_jobs.get_job(job_id)
    if not job:
        return

    try:
        job.status = "running"
        job.progress = 0

        results_collected = []
        
        def on_page(result: CrawlResult):
            """Callback fired after each page."""
            results_collected.append({
                "url": result.url,
                "status": result.status_code,
                "content_type": result.content_type,
                "title": result.title,
                "depth": result.depth,
                "links_found": len(result.links),
                "error": result.error,
                "elapsed_ms": result.elapsed_ms,
                "timing": result.timing,
                "readability": result.readability,
                "assets": result.assets,
                "metadata": result.metadata,
            })

        def on_progress(stats: CrawlStats):
            """Callback for progress updates."""
            if stats.total_pages > 0:
                job.progress = min(
                    int((stats.successful + stats.failed) / request.max_pages * 100), 
                    100
                )

        # Initialize crawler
        crawler = RecursiveCrawler(
            seed_url=request.url,
            max_depth=request.max_depth,
            max_pages=request.max_pages,
            allowed_domains=request.allowed_domains,
            blocked_domains=request.blocked_domains,
            respect_robots=request.respect_robots,
            timeout=request.timeout,
            follow_external=request.follow_external,
            workers=request.workers,
            on_page=on_page,
            on_progress=on_progress,
        )

        # Execute crawl
        await crawler.crawl()
        stats = crawler.get_stats()

        # Store results
        job.result = {
            "pages": results_collected,
            "stats": {
                "total_pages": stats.total_pages,
                "successful": stats.successful,
                "failed": stats.failed,
                "html_pages": stats.html_pages,
                "pdf_files": stats.pdf_files,
                "images": stats.images,
                "other_files": stats.other_files,
                "total_time_sec": round(stats.total_time_sec, 2),
                "pages_per_second": round(stats.pages_per_second, 2),
            },
            "queue_stats": crawler.scheduler.get_stats(),
        }
        job.status = "completed"
        job.progress = 100

    except Exception as e:
        job.status = "failed"
        job.error = str(e)


@router.post("/recursive", summary="Start recursive crawl")
async def start_recursive_crawl(request: RecursiveCrawlRequest, background_tasks: BackgroundTasks):
    """
    Start a recursive website crawl with queue-based URL discovery.
    
    Returns job_id immediately. Use /crawl/recursive/status/{job_id} to check progress.
    
    Features:
    - Depth-limited crawling
    - Domain filtering
    - robots.txt compliance
    - URL deduplication
    - Content-type detection
    - Real-time progress updates
    """
    # Validate URL
    if not request.url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url", "URL must start with http:// or https://")

    # Check if another crawl is running
    active = [j for j in _crawl_jobs.list_jobs() if j["status"] == "running"]
    if active:
        return ApiResponse.fail(
            "queue",
            "concurrent_limit",
            f"Another crawl is in progress (job_id: {active[0]['job_id']}). Wait for it to complete."
        )

    # Create job
    job = _crawl_jobs.create(job_type="recursive_crawl")
    job.metadata = {
        "seed_url": request.url,
        "max_depth": request.max_depth,
        "max_pages": request.max_pages,
    }

    # Start background task
    background_tasks.add_task(_execute_recursive_crawl, job.job_id, request)

    return ApiResponse.ok({
        "job_id": job.job_id,
        "status": job.status,
        "message": f"Recursive crawl started. Seed: {request.url}",
        "poll_url": f"/crawl/recursive/status/{job.job_id}",
    })


@router.get("/recursive/status/{job_id}", summary="Get crawl status")
async def get_crawl_status(job_id: str):
    """Get status and results of a recursive crawl job."""
    job = _crawl_jobs.get_job(job_id)
    if not job:
        return ApiResponse.fail("job", "not_found", f"Job {job_id} not found")

    response_data = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }

    if job.status == "completed":
        response_data["result"] = job.result
    elif job.status == "failed":
        response_data["error"] = job.error

    return ApiResponse.ok(response_data)


@router.get("/recursive/jobs", summary="List all crawl jobs")
async def list_crawl_jobs():
    """List all recursive crawl jobs."""
    jobs = _crawl_jobs.list_jobs()
    return ApiResponse.ok({"jobs": jobs, "count": len(jobs)})


@router.delete("/recursive/{job_id}", summary="Delete crawl job")
async def delete_crawl_job(job_id: str):
    """Delete a crawl job by ID."""
    if _crawl_jobs.delete_job(job_id):
        return ApiResponse.ok({"deleted": job_id})
    return ApiResponse.fail("job", "not_found", f"Job {job_id} not found")
