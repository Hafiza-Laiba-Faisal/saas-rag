"""
Scraper Service Client — bridges RAG engine with the enhanced scraper microservice.
Backward-compatible with existing ScraperService API.
"""

import os
import json
import uuid
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx

from rbs_rag.config import AppConfig
from rbs_rag.store import SQLiteRagStore
from rbs_rag.engine import RagEngine
from rbs_rag.document_loaders import LoadedDocument

log = logging.getLogger(__name__)


@dataclass
class ScrapeJob:
    job_id: str
    url: str
    status: str = "pending"
    crawl: bool = False
    results: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "status": self.status,
            "crawl": self.crawl,
            "results": self.results,
            "error": self.error,
        }


class ScraperService:
    def __init__(self):
        self.base_url = os.getenv("SCRAPER_SERVICE_URL", "http://scraper_service:8000")
        self.deepcrawl_api_key = os.getenv("DEEPCRAWL_API_KEY", "")
        self._http = httpx.Client(timeout=120.0)
        self._jobs: dict[str, ScrapeJob] = {}

    def _call_api(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                r = self._http.get(url, params=payload)
            else:
                r = self._http.post(url, json=payload or {})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("Scraper API call failed: %s %s — %s", method, endpoint, e)
            return {"success": False, "errors": [{"detail": str(e)}]}

    def health(self) -> dict:
        return self._call_api("GET", "/")

    def get_platforms(self) -> list:
        data = self._call_api("GET", "/platforms")
        return data.get("platforms", [])

    # ── Legacy API (backward-compatible) ──────────────────────────────────────

    async def scrape_url(self, url: str) -> ScrapeJob:
        job_id = uuid.uuid4().hex[:12]
        result = self._call_api("POST", "/crawl", {"url": url, "format": "markdown"})
        job = ScrapeJob(job_id=job_id, url=url, status="completed", crawl=False)
        if result.get("success"):
            data = result.get("data", {})
            text = data.get("markdown") or data.get("text", "")
            meta = {
                "url": url,
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "scraped_at": datetime.utcnow().isoformat(),
                "word_count": len(text.split()),
            }
            job.results = [{"text": text, "metadata": meta}]
            job.status = "completed"
        else:
            job.status = "failed"
            job.error = str(result.get("errors", "Unknown error"))
        self._jobs[job_id] = job
        return job

    async def crawl_url(self, url: str, max_pages: int = 50, max_depth: int = 3, full_site: bool = False) -> ScrapeJob:
        job_id = uuid.uuid4().hex[:12]
        result = self._call_api("POST", "/crawl/recursive", {
            "url": url,
            "max_pages": max_pages if not full_site else 200,
            "max_depth": max_depth if not full_site else 10,
        })
        job = ScrapeJob(job_id=job_id, url=url, status="pending", crawl=True)
        if result.get("success"):
            job.status = "running"
            job.job_id = result.get("data", {}).get("job_id", job_id)
        else:
            job.status = "failed"
            job.error = str(result.get("errors", "Unknown error"))
        self._jobs[job_id] = job
        return job

    async def get_job(self, job_id: str) -> ScrapeJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[ScrapeJob]:
        return list(self._jobs.values())

    # ── New enhanced API ──────────────────────────────────────────────────────

    def crawl_single(self, url: str, format: str = "markdown") -> dict:
        return self._call_api("POST", "/crawl", {"url": url, "format": format})

    def crawl_smart(self, url: str, timeout: int = 30) -> dict:
        payload = {"url": url, "timeout": timeout}
        if self.deepcrawl_api_key:
            payload["deepcrawl_api_key"] = self.deepcrawl_api_key
        return self._call_api("POST", "/crawl/smart", payload)

    def crawl_recursive(self, url: str, max_depth: int = 2, max_pages: int = 50,
                         respect_robots: bool = True, workers: int = 1,
                         allowed_domains: list[str] | None = None) -> dict:
        return self._call_api("POST", "/crawl/recursive", {
            "url": url, "max_depth": max_depth, "max_pages": max_pages,
            "respect_robots": respect_robots, "workers": workers,
            "allowed_domains": allowed_domains,
        })

    def get_recursive_status(self, job_id: str) -> dict:
        return self._call_api("GET", f"/crawl/recursive/status/{job_id}")

    def list_recursive_jobs(self) -> list:
        data = self._call_api("GET", "/crawl/recursive/jobs")
        return data if isinstance(data, list) else data.get("jobs", [])

    def delete_recursive_job(self, job_id: str) -> dict:
        try:
            r = self._http.delete(f"{self.base_url}/crawl/recursive/{job_id}")
            return r.json() if r.content else {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def scrape_wordpress(self, url: str, max_pages: int = 10,
                          include_pages: bool = True, include_media: bool = True) -> dict:
        return self._call_api("POST", "/scrape/wordpress", {
            "url": url, "max_pages": max_pages,
            "include_pages": include_pages, "include_media": include_media,
        })

    def scrape_facebook(self, page_url: str, c_user: str = "", xs: str = "",
                         max_posts: int = 20, scroll_rounds: int = 5,
                         date_from: str = "", date_to: str = "") -> dict:
        return self._call_api("POST", "/scrape/fb-posts", {
            "page_url": page_url, "c_user": c_user, "xs": xs,
            "max_posts": max_posts, "scroll_rounds": scroll_rounds,
            "date_from": date_from, "date_to": date_to,
        })

    def get_fb_job_status(self, job_id: str) -> dict:
        return self._call_api("GET", f"/scrape/fb-posts/status/{job_id}")

    def scrape_profile(self, platform: str, username: str,
                        browser: str = "chrome", proxy: str | None = None) -> dict:
        return self._call_api("POST", "/scrape/profile", {
            "platform": platform, "username": username,
            "browser": browser, "proxy": proxy,
        })


def scrape_and_ingest(
    config: AppConfig,
    store: SQLiteRagStore,
    url: str,
    tenant_id: str,
    knowledge_base_id: str = "default",
    scrape_type: str = "single",
    **kwargs
) -> dict:
    """
    High-level helper: scrape a URL via the scraper service,
    save as a document with rich metadata, and auto-ingest into the RAG pipeline.
    """
    client = ScraperService(config)

    if scrape_type == "smart":
        result = client.crawl_smart(url, timeout=kwargs.get("timeout", 30))
    else:
        result = client.crawl_single(url, format="markdown")

    if not result.get("success"):
        return {"status": "failed", "error": result.get("errors", [])}

    data = result.get("data", {})
    title = data.get("title", url)
    text = data.get("markdown") or data.get("json", {}).get("markdown", "") or data.get("text", "")
    description = data.get("description", "")

    if not text.strip():
        return {"status": "failed", "error": "No text extracted from URL"}

    scraped_meta = {
        "source_url": url,
        "title": title,
        "description": description,
        "scrape_type": scrape_type,
        "scraped_at": datetime.utcnow().isoformat(),
        "word_count": len(text.split()),
        "content_type": "web_scrape",
    }
    if "quality_score" in data:
        scraped_meta["quality_score"] = data["quality_score"]
        scraped_meta["quality_level"] = data.get("quality_level", "unknown")

    tenant_dir = Path(config.rag_root_dir) / "tenants" / tenant_id / "documents"
    tenant_dir.mkdir(parents=True, exist_ok=True)

    site_slug = url.replace("https://", "").replace("http://", "").split("/")[0]
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60]
    filename = f"scraped_{site_slug}_{safe_title}_{uuid.uuid4().hex[:8]}.md"
    filepath = tenant_dir / filename

    content = f"""---
url: {url}
title: {title}
description: {description}
scrape_type: {scrape_type}
scraped_at: {scraped_meta['scraped_at']}
word_count: {scraped_meta['word_count']}
---

{text}
"""
    filepath.write_text(content, encoding="utf-8")

    doc_id = hashlib.sha1(str(filepath.resolve()).encode("utf-8")).hexdigest()
    doc = LoadedDocument(
        document_id=doc_id,
        path=str(filepath),
        name=filename,
        document_type="md",
        text=text,
        metadata=scraped_meta,
        ocr_applied=False,
        ocr_engine=None,
        page_count=None,
    )

    engine = RagEngine(config, Path(config.rag_root_dir))
    chunker = engine.chunker
    embedding_provider = engine.embedding_provider

    chunks = chunker.chunk(doc, tenant_id, knowledge_base_id)
    embeddings = embedding_provider.embed([c.text for c in chunks])
    for i, c in enumerate(chunks):
        c.embedding = embeddings[i]

    store.upsert_document(doc, tenant_id, knowledge_base_id, source="scrape", source_url=url)
    store.upsert_chunks(chunks)

    if engine.vector_store and engine.vector_store.initialized:
        try:
            engine.vector_store.upsert_chunks("rag_chunks", chunks)
        except Exception:
            pass

    return {
        "status": "completed",
        "document": filename,
        "title": title,
        "word_count": len(text.split()),
        "chunks": len(chunks),
        "metadata": scraped_meta,
    }
