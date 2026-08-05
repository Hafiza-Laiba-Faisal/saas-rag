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
    workers: int = Field(4, ge=1, le=20, description="Concurrent workers for the recursive discovery crawl")
    respect_robots: bool = Field(False, description="Honor robots.txt during recursive discovery")


def _run_full_crawl(job_id: str, req: FullCrawlRequest):
    import asyncio
    from scrapers.site_crawler import SiteCrawler

    job = default_job_store.get_job(job_id)
    if not job:
        return

    CRAWL_TIMEOUT = 3600  # 1 hour max

    def update_job(pct: int, msg: str):
        job.progress = pct
        job.message = msg
        default_job_store.update(job)

    def persist():
        default_job_store.update(job)

    async def run():
        job.status = "running"
        job.progress = 0
        job.message = "Starting full site crawl..."
        persist()

        crawler = SiteCrawler(output_base=str(_output_base))
        crawler.set_progress_callback(update_job)
        result = await asyncio.wait_for(
            crawler.crawl(
                url=req.url,
                max_pages=req.max_pages,
                download_images=req.download_images,
                download_pdfs=req.download_pdfs,
                workers=req.workers,
                respect_robots=req.respect_robots,
            ),
            timeout=CRAWL_TIMEOUT,
        )

        if result.error:
            job.status = "error"
            job.error = result.error
            job.message = f"Crawl failed: {result.error}"
            persist()
            return

        job.result = {
            "url": result.url,
            "strategy": "site_crawler",
            "languages": result.languages,
            "pages_found": result.pages_crawled,
            "pages_failed": result.pages_failed,
            "content_files": result.content_files,
            "content_files_count": len(result.content_files),
            "images_discovered": result.images_total,
            "images_downloaded": result.images_downloaded,
            "images_content": result.images_content,
            "images_decorative": result.images_decorative,
            "pdfs_discovered": result.pdfs_found,
            "pdfs_downloaded": result.pdfs_downloaded,
            "pages_by_language": {lang: len(pages) for lang, pages in result.pages_by_language.items()},
            "output_dir": result.output_dir,
            "elapsed_ms": result.elapsed_ms,
        }
        job.status = "done"
        job.progress = 100
        job.message = (
            f"Crawl complete — {result.pages_crawled} pages "
            f"({len(result.content_files)} with content), "
            f"{result.images_downloaded} images, "
            f"{result.pdfs_downloaded} PDFs"
        )
        persist()

    try:
        asyncio.run(run())
    except asyncio.TimeoutError:
        job.status = "error"
        job.error = "Crawl timed out"
        job.message = "Crawl timed out after 1 hour"
        persist()
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.message = str(e)
        persist()


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



@router.get("/full/{job_id}/output", summary="Get crawl output manifest for RAG sync")
async def get_crawl_output(job_id: str):
    """
    Returns complete crawl output manifest for RAG service sync.
    Includes page details, images, PDFs, and paths for downloading content.
    """
    job = default_job_store.get_job(job_id)
    if not job:
        return ApiResponse.fail("jobs", "not_found", f"No job found with id {job_id}")
    
    if job.status not in ["done", "completed"]:
        return ApiResponse.fail("jobs", "not_ready", f"Job status is {job.status}, not ready for sync")
    
    if not job.result or not job.result.get("output_dir"):
        return ApiResponse.fail("jobs", "no_output", "Crawl has no output directory")
    
    output_dir = Path(job.result["output_dir"])
    
    # Load index.json
    index_path = output_dir / "index.json"
    if not index_path.exists():
        return ApiResponse.fail("jobs", "no_index", "index.json not found in output directory")
    
    try:
        import json
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        return ApiResponse.fail("jobs", "invalid_index", f"Failed to load index.json: {e}")
    
    # Load crawl_summary.json if available
    summary = {}
    summary_path = output_dir / "crawl_summary.json"
    if summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            pass
    
    # Build page manifest with detailed info
    pages = []
    # Support both new format (pages[]) and old format (pages_flat[])
    page_entries = index_data.get("pages", []) or index_data.get("pages_flat", [])
    for page_entry in page_entries:
        page_id = page_entry.get("page_id") or ""
        url = page_entry.get("url", "")
        language = page_entry.get("language", "default")
        section = page_entry.get("section", "General")
        changed = page_entry.get("changed", True)

        pages.append({
            "page_id": page_id,
            "url": url,
            "title": page_entry.get("title", ""),
            "language": language,
            "section": section,
            "changed": changed,
            "clean_text_path": page_entry.get("clean_text", f"clean_text/{page_id}.md") if page_id else page_entry.get("file", ""),
            "metadata_path": page_entry.get("metadata", f"metadata/{page_id}.metadata.json") if page_id else "",
            "raw_html_path": page_entry.get("raw_html", f"raw_html/{page_id}.html") if page_id else "",
            "word_count": page_entry.get("word_count", 0),
        })
    
    # Load images.json if available
    images = []
    images_json_path = output_dir / "images.json"
    if images_json_path.exists():
        try:
            with open(images_json_path, "r", encoding="utf-8") as f:
                images = json.load(f)
        except Exception:
            pass
    
    # Build response
    manifest = {
        "job_id": job_id,
        "output_dir": str(output_dir),
        "site": index_data.get("site", ""),
        "crawled_at": index_data.get("crawled_at", ""),
        "strategy": index_data.get("strategy", ""),
        "pages": pages,
        "pages_by_language": index_data.get("pages_by_language", {}),
        "images": images[:100],  # Limit to 100 for response size
        "pdfs": index_data.get("pdfs", [])[:50],
        "stats": index_data.get("stats", {}),
        "summary": summary,
        "changed_pages": index_data.get("changed_pages", []),
        "unchanged_pages": index_data.get("unchanged_pages", []),
    }
    
    return ApiResponse.ok(manifest)


@router.get("/full/{job_id}/report", summary="Get crawl summary report")
async def get_crawl_report(job_id: str):
    """
    Returns crawl_summary.json with statistics and metrics.
    """
    job = default_job_store.get_job(job_id)
    if not job:
        return ApiResponse.fail("jobs", "not_found", f"No job found with id {job_id}")
    
    if not job.result or not job.result.get("output_dir"):
        return ApiResponse.fail("jobs", "no_output", "Crawl has no output directory")
    
    output_dir = Path(job.result["output_dir"])
    summary_path = output_dir / "crawl_summary.json"
    
    if not summary_path.exists():
        return ApiResponse.fail("jobs", "no_summary", "crawl_summary.json not found")
    
    try:
        import json
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        return ApiResponse.ok(summary)
    except Exception as e:
        return ApiResponse.fail("jobs", "invalid_summary", f"Failed to load summary: {e}")
