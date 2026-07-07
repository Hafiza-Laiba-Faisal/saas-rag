"""Scraper Service for RAG integration"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from rbs_rag.scraper.config import ScraperConfig, get_config
from rbs_rag.scraper.core.engine import ScraperEngine, ScrapeResult
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class ScrapeJob:
    """Represents a scraping job."""
    def __init__(
        self,
        url: str,
        job_id: str = None,
        status: str = "pending",
        max_pages: int = 10,
        max_depth: int = 2,
        crawl: bool = False,
    ):
        self.job_id = job_id or str(uuid.uuid4())
        self.url = url
        self.status = status
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.crawl = crawl
        self.result: Optional[ScrapeResult] = None
        self.results: list[ScrapeResult] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.completed_at: Optional[float] = None

    @property
    def processing_time_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.created_at) * 1000
        return 0.0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "processing_time_ms": self.processing_time_ms,
            "result": self.result.to_dict() if self.result else None,
        }


class ScraperService:
    """Web scraping service integrated with RAG pipeline."""

    def __init__(self, config: ScraperConfig = None):
        self.config = config or get_config()
        self._engine: Optional[ScraperEngine] = None
        self._jobs: dict[str, ScrapeJob] = {}

    async def start(self):
        """Initialize the scraper service."""
        if self._engine is None:
            self._engine = ScraperEngine(self.config)
            await self._engine.start()
        return self

    async def close(self):
        """Close the scraper service."""
        if self._engine:
            await self._engine.close()
            self._engine = None

    async def scrape_url(self, url: str) -> ScrapeJob:
        """Scrape a single URL as a job."""
        if not self._engine:
            await self.start()

        job = ScrapeJob(url=url, crawl=False)
        self._jobs[job.job_id] = job

        try:
            job.status = "running"
            result = await self._engine.scrape(url)
            job.result = result
            job.status = "completed" if result.is_success else "failed"
            job.error = result.error
            job.completed_at = time.time()
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = time.time()

        return job

    async def crawl_url(self, url: str, max_pages: int = 10, max_depth: int = 2) -> ScrapeJob:
        """Crawl a URL (scrape page + its links)."""
        if not self._engine:
            await self.start()

        job = ScrapeJob(url=url, crawl=True, max_pages=max_pages, max_depth=max_depth)
        self._jobs[job.job_id] = job

        try:
            job.status = "running"
            results = await self._engine.crawl_domain(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
            )
            job.results = results
            job.status = "completed" if any(r.is_success for r in results) else "failed"
            job.completed_at = time.time()
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = time.time()

        return job

    def get_job(self, job_id: str) -> Optional[ScrapeJob]:
        """Get a specific job."""
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[ScrapeJob]:
        """List recent jobs."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _content_to_markdown_file(self, result: ScrapeResult, output_dir: Path) -> Path:
        """Save scraped content as markdown file."""
        safe_name = f"scraped_{uuid.uuid4().hex[:8]}.md"
        file_path = output_dir / safe_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(result.to_text(), encoding="utf-8")
        return file_path