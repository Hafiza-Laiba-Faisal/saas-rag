"""
Job store — auto-selects Redis when available, falls back to in-memory.
Same API for all callers.
"""

from __future__ import annotations
import os
import json
import uuid
import threading
import logging
from datetime import datetime
from typing import Optional, Literal
from config.settings import MAX_JOBS_IN_MEMORY, MAX_CONCURRENT_JOBS

log = logging.getLogger(__name__)

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


class _InMemoryStore:
    """Thread-safe in-memory job registry."""

    def __init__(self, max_jobs=MAX_JOBS_IN_MEMORY, max_concurrent=MAX_CONCURRENT_JOBS):
        self._jobs: dict[str, ScrapeJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._max_concurrent = max_concurrent

    def create(self, job_type: str = "scrape") -> ScrapeJob:
        job = ScrapeJob(job_type=job_type)
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j.status == "running")
            if running >= self._max_concurrent:
                raise RuntimeError("Max concurrent jobs reached")
            self._jobs[job.job_id] = job
            self._purge_old()
        return job

    def get(self, job_id: str) -> Optional[ScrapeJob]:
        return self._jobs.get(job_id)

    def get_job(self, job_id: str) -> Optional[ScrapeJob]:
        return self.get(job_id)

    def update(self, job: ScrapeJob) -> None:
        """Update job in store (in-memory: already in dict by reference, just ensure stored)."""
        with self._lock:
            self._jobs[job.job_id] = job

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self._jobs.values()]

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def _purge_old(self):
        if len(self._jobs) > self._max_jobs:
            oldest = list(self._jobs.keys())[:-self._max_jobs]
            for k in oldest:
                del self._jobs[k]


class _RedisStore:
    """Redis-backed job store."""

    def __init__(self, prefix: str = "scraper_job:"):
        self._client = None
        self._enabled = False
        self._prefix = prefix
        self._fallback: dict[str, ScrapeJob] = {}
        self._init()

    def _init(self):
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", None)
        try:
            import redis as sync_redis
            self._client = sync_redis.Redis(
                host=host, port=port, password=password or None,
                decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
            )
            self._client.ping()
            self._enabled = True
            log.info("Redis job store initialized")
        except Exception as e:
            log.warning("Redis job store unavailable — in-memory fallback: %s", e)

    def _key(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}"

    def create(self, job_type: str = "scrape") -> ScrapeJob:
        job = ScrapeJob(job_type=job_type)
        if self._enabled and self._client:
            try:
                self._client.setex(self._key(job.job_id), 86400, json.dumps(job.to_dict(), default=str))
            except Exception as e:
                log.warning("Redis create failed: %s", e)
                self._fallback[job.job_id] = job
        else:
            self._fallback[job.job_id] = job
        return job

    def update(self, job: ScrapeJob) -> None:
        if self._enabled and self._client:
            try:
                self._client.setex(self._key(job.job_id), 86400, json.dumps(job.to_dict(), default=str))
            except Exception as e:
                log.warning("Redis update failed: %s", e)

    def get(self, job_id: str) -> Optional[ScrapeJob]:
        if self._enabled and self._client:
            try:
                raw = self._client.get(self._key(job_id))
                if raw:
                    data = json.loads(raw)
                    job = ScrapeJob()
                    for k in ScrapeJob.__slots__:
                        if k in data:
                            if k == "created_at" and isinstance(data[k], str):
                                try:
                                    setattr(job, k, datetime.fromisoformat(data[k]))
                                except ValueError:
                                    setattr(job, k, data[k])
                            else:
                                setattr(job, k, data[k])
                    return job
            except Exception:
                pass
        return self._fallback.get(job_id)

    def get_job(self, job_id: str) -> Optional[ScrapeJob]:
        return self.get(job_id)

    def list_jobs(self) -> list[dict]:
        result = []
        if self._enabled and self._client:
            try:
                keys = self._client.keys(f"{self._prefix}*")
                for k in keys:
                    raw = self._client.get(k)
                    if raw:
                        result.append(json.loads(raw))
            except Exception:
                pass
        result.extend(j.to_dict() for j in self._fallback.values())
        return result

    def delete_job(self, job_id: str) -> bool:
        if self._enabled and self._client:
            try:
                deleted_count = self._client.delete(self._key(job_id))
                fallback_deleted = self._fallback.pop(job_id, None) is not None
                return deleted_count > 0 or fallback_deleted
            except Exception:
                pass
        return self._fallback.pop(job_id, None) is not None


# ── Select backend ──────────────────────────────────────────────────────────
_use_redis = os.getenv("REDIS_ENABLED", "").lower() in ("1", "true", "yes")
if _use_redis:
    try:
        default_job_store: _RedisStore = _RedisStore()
    except Exception:
        default_job_store: _InMemoryStore = _InMemoryStore()
else:
    default_job_store: _InMemoryStore = _InMemoryStore()
