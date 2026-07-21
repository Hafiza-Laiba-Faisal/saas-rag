from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from jobs.job_store import default_job_store
from schemas.base import ApiResponse

router = APIRouter(prefix="/crawl", tags=["full-crawl"])


_output_base = Path("crawl_output")


class FullCrawlRequest(BaseModel):
    url: str = Field(..., description="Site URL to crawl")
    max_depth: int = Field(3, ge=1, le=10, description="Max crawl depth")
    max_pages: int = Field(50, ge=1, le=1000, description="Max pages to crawl")
    download_images: bool = Field(True, description="Download images")
    download_pdfs: bool = Field(True, description="Download PDFs")


def _run_full_crawl(job_id: str, req: FullCrawlRequest):
    import asyncio
    from scrapers.auto_crawler import AutoCrawler

    job = default_job_store.get_job(job_id)
    if not job:
        return

    CRAWL_TIMEOUT = 600

    def update_job(pct: int, msg: str):
        job.progress = pct
        job.message = msg

    async def run():
        job.status = "running"
        job.progress = 0
        job.message = "Starting full site crawl..."

        crawler = AutoCrawler(output_base=str(_output_base))
        crawler.set_progress_callback(update_job)
        result = await asyncio.wait_for(
            crawler.crawl(
                url=req.url,
                max_depth=req.max_depth,
                max_pages=req.max_pages,
                download_images=req.download_images,
                download_pdfs=req.download_pdfs,
            ),
            timeout=CRAWL_TIMEOUT,
        )

        if result.error:
            job.status = "error"
            job.error = result.error
            job.message = f"Crawl failed: {result.error}"
            return

        job.result = {
            "url": result.url,
            "is_wordpress": result.is_wordpress,
            "strategy": result.strategy_used,
            "languages": result.languages,
            "pages_found": result.stats.get("pages_found", 0),
            # Full list (title/url/lang/file/text_length) so callers can fetch each
            # page's actual extracted content, not just a count.
            "content_files": result.content_files,
            "content_files_count": len(result.content_files),
            "images_discovered": result.stats.get("images_discovered", 0),
            "images_downloaded": result.stats.get("images_downloaded", 0),
            "pdfs_discovered": result.stats.get("pdfs_discovered", 0),
            "pdfs_downloaded": result.stats.get("pdfs_downloaded", 0),
            "pages_by_language": {
                lang: len(pages)
                for lang, pages in result.pages_by_language.items()
            },
            "output_dir": result.output_dir,
            "elapsed_ms": result.elapsed_ms,
        }
        job.status = "done"
        job.progress = 100
        job.message = (
            f"Crawl complete — {result.stats.get('pages_found', 0)} pages "
            f"({len(result.content_files)} with extracted content), "
            f"{result.stats.get('images_downloaded', 0)} images, "
            f"{result.stats.get('pdfs_downloaded', 0)} PDFs"
        )

    try:
        asyncio.run(run())
    except asyncio.TimeoutError:
        job.status = "error"
        job.error = "Crawl timed out after 5 minutes"
        job.message = "Crawl timed out — site may have too many images or slow responses"
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.message = str(e)


@router.post("/full", summary="Full site crawl — auto-detect, extract text, download images/PDFs")
async def start_full_crawl(req: FullCrawlRequest):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url", "URL must start with http:// or https://")

    try:
        job = default_job_store.create(job_type="full_crawl")
    except RuntimeError as e:
        return ApiResponse.fail("jobs", "too_many_jobs", str(e))

    t = threading.Thread(
        target=_run_full_crawl,
        args=(job.job_id, req),
        daemon=True,
    )
    t.start()

    return ApiResponse.ok({
        "job_id": job.job_id,
        "status": "pending",
        "message": "Full crawl started",
        "poll_url": f"/crawl/full/status/{job.job_id}",
    })


@router.get("/full/status/{job_id}", summary="Poll full crawl job status")
async def get_full_crawl_status(job_id: str):
    job = default_job_store.get_job(job_id)
    if not job:
        return ApiResponse.fail("jobs", "not_found", f"No job found with id {job_id}")

    resp = job.to_dict()
    result_data = resp.get("result")
    if result_data:
        resp["result"] = result_data
    return ApiResponse.ok(resp)


@router.get("/full/jobs", summary="List all full crawl jobs")
async def list_fulldefault_job_store():
    jobs = default_job_store.list_jobs()
    return ApiResponse.ok({"jobs": jobs, "count": len(jobs)})


@router.delete("/full/{job_id}", summary="Delete a full crawl job")
async def delete_full_crawl_job(job_id: str):
    if not default_job_store.delete_job(job_id):
        return ApiResponse.fail("jobs", "not_found", f"No job found with id {job_id}")
    return ApiResponse.ok({"deleted": job_id})


@router.get("/full/output/{job_id}/{file_path:path}", summary="Serve crawled file (image, PDF, page markdown)")
async def serve_crawl_file(job_id: str, file_path: str):
    job = default_job_store.get_job(job_id)
    if not job:
        return ApiResponse.fail("jobs", "not_found", "Job not found or expired")

    if not job.result or not job.result.get("output_dir"):
        return ApiResponse.fail("jobs", "no_output", "Crawl has no output directory")

    fpath = Path(job.result["output_dir"]) / file_path
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(404, f"File not found: {file_path}")

    return FileResponse(str(fpath))
