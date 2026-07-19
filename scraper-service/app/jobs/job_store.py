"""
In-memory background job store.
Isolated from main.py — importable and testable independently.
Future: swap with Celery/ARQ/Redis queue without touching routes.
"""

from __future__ import annotations
import uuid
import threading
from datetime import datetime
from typing import Optional, Literal
from config.settings import MAX_JOBS_IN_MEMORY, MAX_CONCURRENT_JOBS


JobStatusType = Literal["pending", "running", "done", "error", "completed", "failed"]


class ScrapeJob:
    __slots__ = ("job_id", "job_type", "status", "progress", "message", "result", "error", "metadata", "created_at")

    def __init__(self, job_type: str = "scrape"):
        self.job_id:    str                  = str(uuid.uuid4())[:8]
        self.job_type:  str                  = job_type
        self.status:    JobStatusType        = "pending"
        self.progress:  int                  = 0
        self.message:   str                  = ""
        self.result:    Optional[dict]       = None
        self.error:     str                  = ""
        self.metadata:  dict                 = {}
        self.created_at: datetime            = datetime.utcnow()

    def to_dict(self) -> dict:
        d = {}
        for k in self.__slots__:
            val = getattr(self, k)
            if isinstance(val, datetime):
                val = val.isoformat()
            d[k] = val
        return d


class JobStore:
    """Thread-safe in-memory job registry."""

    def __init__(
        self,
        max_jobs:        int = MAX_JOBS_IN_MEMORY,
        max_concurrent:  int = MAX_CONCURRENT_JOBS,
    ):
        self._jobs:          dict[str, ScrapeJob] = {}
        self._lock           = threading.Lock()
        self._max_jobs       = max_jobs
        self._max_concurrent = max_concurrent

    def create(self, job_type: str = "scrape") -> ScrapeJob:
        """Create a new job."""
        job = ScrapeJob(job_type=job_type)
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j.status == "running")
            if running >= self._max_concurrent:
                raise RuntimeError(
                    f"Ek scrape job pehle se chal rahi hai — "
                    f"wait karo ya baad mein try karo."
                )
            self._jobs[job.job_id] = job
            self._purge_old()
        return job

    def get(self, job_id: str) -> Optional[ScrapeJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)
    
    def get_job(self, job_id: str) -> Optional[ScrapeJob]:
        """Alias for get() - for compatibility."""
        return self.get(job_id)

    def all(self) -> list[ScrapeJob]:
        """Get all jobs."""
        with self._lock:
            return list(self._jobs.values())
    
    def list_jobs(self) -> list[dict]:
        """Get all jobs as dictionaries."""
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID."""
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    def _purge_old(self) -> None:
        """Keep only the last N jobs. Call inside lock."""
        if len(self._jobs) > self._max_jobs:
            oldest_keys = list(self._jobs.keys())[:-self._max_jobs]
            for k in oldest_keys:
                del self._jobs[k]


# Module-level default instance
default_job_store = JobStore()
