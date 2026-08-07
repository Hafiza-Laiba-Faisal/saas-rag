from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, UploadFile, File, Header, HTTPException, BackgroundTasks, Depends, Query, Response, Body
from datetime import datetime, timezone
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rbs_rag.config import AppConfig, StorageConfig, EmbeddingConfig, RetrievalConfig, ChunkingConfig, QdrantConfig, RateLimitConfig, SecurityConfig, ObservabilityConfig
from rbs_rag.llm import LLMSettings
from rbs_rag.engine import RagEngine
from rbs_rag.store import SQLiteRagStore
from rbs_rag.document_loaders import SUPPORTED_EXTENSIONS, _document_id, load_document
from rbs_rag.cloud_sync import sync_cloud_documents
from rbs_rag.security import detect_prompt_injection, generate_jwt, verify_jwt
from rbs_rag.metrics import MetricsMiddleware, metrics_export, DOCUMENTS_INGESTED, CHUNKS_CREATED, CHUNKS_RETRIEVED, LLM_REQUESTS, LLM_DURATION, PROMPT_INJECTIONS_BLOCKED, ACTIVE_TENANTS, ENGINE_UPTIME
from rbs_rag.web.admin_db import AdminStore
from rbs_rag.provisioning import provision_tenant
from rbs_rag.ocr.service import get_ocr_service, init_ocr_service
from rbs_rag.services.scraper_service import ScraperService
from rbs_rag.models import StreamingChunk
from rbs_rag.cache import redis_client

log = logging.getLogger(__name__)

ROOT_DIR = Path(os.getenv("RAG_ROOT_DIR", ".rbs_rag")).resolve()
ADMIN_DB_PATH = ROOT_DIR / "admin.db"
TENANTS_DIR = ROOT_DIR / "tenants"
CRAWL_OUTPUT_DIR = ROOT_DIR / "crawl-output"

admin_store = AdminStore(ADMIN_DB_PATH)
ingestion_status: dict[str, dict[str, Any]] = {}
_scraper_service: ScraperService | None = None
_server_start_time = time.time()
_engine_cache: dict[str, RagEngine] = {}

TENANTS_DIR.mkdir(parents=True, exist_ok=True)


def _tenant_db_path(tenant_id: str, tenant: dict | None = None) -> Path:
    """Resolve a tenant's per-tenant rag.db path from admin.db (db_path column)."""
    if tenant is None:
        tenant = admin_store.get_tenant(tenant_id) or {}
    db_path = tenant.get("db_path")
    if db_path:
        p = Path(db_path)
        return p if p.is_absolute() else (ROOT_DIR / p)
    return TENANTS_DIR / tenant_id / "rag.db"


def _tenant_connection(db_path: Path):
    """Open a raw per-tenant SQLite connection with the standard PRAGMAs."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _normalize_title(title: str) -> str:
    """Normalize a title for matching: lowercase, collapse whitespace, drop non-alphanumerics."""
    return re.sub(r"[^a-z0-9]+", "", title.strip().lower())


def _make_relevant_filename(title: str = "", url: str = "", docs_dir: Path | None = None, prefix: str = "scraped") -> str:
    """Generate a clean, relevant, human-readable filename based on page title or URL path."""
    base = ""
    if title and title.strip():
        clean_title = re.sub(r'\s*[\-|–|—]\s*.*$', '', title.strip(), flags=re.IGNORECASE)
        base = clean_title.strip()
    if not base and url:
        parsed = url.rstrip("/").split("/")[-1]
        base = parsed
    if not base:
        base = "page"

    slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', base).strip('_')
    slug = re.sub(r'_+', '_', slug)[:45].lower()
    if not slug:
        slug = "page"

    candidate = f"{prefix}_{slug}.txt"
    if docs_dir and (docs_dir / candidate).exists():
        candidate = f"{prefix}_{slug}_{uuid.uuid4().hex[:4]}.txt"
    return candidate


def _ts_to_epoch(value) -> float:
    """Best-effort parse of a SQLite timestamp (UTC) / ISO string into epoch seconds."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        if "." not in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _scan_existing_urls(tenant_id: str) -> dict[str, str]:
    """Return mapping of {source_url → filename} for all existing scraped files in tenant docs dir.
    Used for duplicate detection before saving a new scrape."""
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    url_map: dict[str, str] = {}
    if not docs_dir.exists():
        return url_map
    # Scan all .txt and .md files (crawl-imported files are named by title,
    # e.g. "Home - Hotel de la Ville.md", not "scraped_*"), indexing each by
    # its Source: header so crawl-imports don't get re-copied on every refresh.
    for pattern in ("*.txt", "*.md"):
        for f in docs_dir.glob(pattern):
            try:
                with f.open("r", encoding="utf-8", errors="ignore") as fp:
                    for _ in range(6):
                        line = fp.readline()
                        if line.startswith("Source:"):
                            url = line.replace("Source:", "").strip()
                            if url:
                                url_map[url] = f.name
                            break
            except Exception:
                pass
    return url_map


def _scraped_source_url(file_path: Path) -> str | None:
    """Read the Source: line from a scraped file header."""
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as fp:
            for _ in range(8):
                line = fp.readline()
                if line.startswith("Source:"):
                    return line.replace("Source:", "").strip()
    except Exception:
        pass
    return None


def _tombstone_path(tenant_id: str) -> Path:
    """Per-tenant JSON file recording source URLs the user has deleted, so the
    crawl-output sync never re-imports them even if the source files remain."""
    return TENANTS_DIR / tenant_id / "deleted_sources.json"


def _load_tombstones(tenant_id: str) -> set[str]:
    try:
        return set(json.loads(_tombstone_path(tenant_id).read_text(encoding="utf-8")))
    except Exception:
        return set()


def _mark_deleted_source(tenant_id: str, source_url: str | None, filename: str | None = None) -> None:
    tombstones = _load_tombstones(tenant_id)
    if source_url:
        tombstones.add(source_url)
    if filename:
        tombstones.add(f"file:{filename}")
    _tombstone_path(tenant_id).write_text(json.dumps(sorted(tombstones)), encoding="utf-8")


def _purge_crawl_output_for_file(source_url: str | None, filename: str) -> None:
    """Remove a deleted document's pages/PDFs from the crawl-output catalog so
    _sync_crawl_outputs_to_tenant won't re-import them on the next list refresh."""
    search_dirs = [
        ROOT_DIR / "crawl-output",
        Path("scraper-service/crawl_output"),
        Path("scraper-service/app/crawl_output"),
    ]
    # Match the tenant filename the sync step would generate for a given md page.
    def _derived_prefix(md_file: Path) -> str:
        try:
            title = f"{md_file.stem} ({md_file.parent.name.upper()})"
            base = _make_relevant_filename(title=title, url=source_url or "", prefix="scraped")
            return base[:-4]  # strip ".txt" -> "scraped_<slug>"
        except Exception:
            return ""

    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        for site_dir in base_dir.iterdir():
            if not site_dir.is_dir():
                continue
            # Remove matching markdown pages (matched by Source: URL or derived filename).
            pages_dir = site_dir / "pages"
            if pages_dir.exists():
                for md_file in pages_dir.rglob("*.md"):
                    remove = False
                    try:
                        with md_file.open("r", encoding="utf-8", errors="ignore") as fp:
                            for _ in range(8):
                                line = fp.readline()
                                if line.startswith("Source:"):
                                    if line.replace("Source:", "").strip() == source_url:
                                        remove = True
                                    break
                    except Exception:
                        pass
                    if not remove:
                        prefix = _derived_prefix(md_file)
                        if prefix and filename.startswith(prefix):
                            remove = True
                    if remove:
                        try:
                            md_file.unlink()
                        except Exception:
                            pass
            # Remove matching downloaded PDFs (matched by filename).
            pdfs_dir = site_dir / "pdfs"
            if pdfs_dir.exists():
                target = pdfs_dir / filename
                if target.exists():
                    try:
                        target.unlink()
                    except Exception:
                        pass


def _sync_crawl_outputs_to_tenant(tenant_id: str, site_url: str | None = None, site_dir: Path | None = None) -> list[dict]:
    """Scan crawler output directories and import completed pages into tenant documents.

    If ``site_dir`` is provided only that site folder is scanned (used after a crawl
    completes). Otherwise, when the tenant has a stored ``crawl_output_dir`` only that
    folder is scanned. Falls back to scanning all known crawler output directories.
    """
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    existing_url_map = _scan_existing_urls(tenant_id)
    deleted_urls = _load_tombstones(tenant_id)

    search_dirs = [
        ROOT_DIR / "crawl-output",
        Path("scraper-service/crawl_output"),
        Path("scraper-service/app/crawl_output"),
    ]

    tenant = admin_store.get_tenant(tenant_id)
    tenant_crawl_dir = tenant.get("crawl_output_dir") if tenant else None

    if site_dir is not None:
        base_dirs: list[Path] = [site_dir]
    elif tenant_crawl_dir:
        base_dirs = [Path(tenant_crawl_dir)]
    else:
        base_dirs = search_dirs

    def _load_site_url_map(site_dir: Path) -> dict[tuple[str, str], str]:
        """Load {(lang, title): url} per page from a crawler site's index.json."""
        index_file = site_dir / "index.json"
        url_map: dict[tuple[str, str], str] = {}
        if not index_file.exists():
            return url_map
        try:
            data = json.loads(index_file.read_text(encoding="utf-8", errors="ignore"))
            by_lang = data.get("pages_by_language") or data.get("pages") or {}
            if isinstance(by_lang, dict):
                for lang, lang_pages in by_lang.items():
                    if isinstance(lang_pages, list):
                        for p in lang_pages:
                            if isinstance(p, dict) and p.get("title") and p.get("url"):
                                key = (str(lang).lower(), _normalize_title(p["title"]))
                                url_map[key] = p["url"]
            elif isinstance(by_lang, list):
                for p in by_lang:
                    if isinstance(p, dict) and p.get("title") and p.get("url"):
                        key = (str(p.get("language", "")).lower(), _normalize_title(p["title"]))
                        url_map[key] = p["url"]
        except Exception:
            pass
        return url_map

    saved_files = []
    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        if site_dir is not None or tenant_crawl_dir:
            site_folders: list[Path] = [base_dir]
        else:
            site_folders = [p for p in base_dir.iterdir() if p.is_dir()]
        for site_dir in site_folders:
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            site_url_map = _load_site_url_map(site_dir)
            for md_file in pages_dir.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8", errors="ignore")
                    if not text.strip():
                        continue
                    lang = md_file.parent.name
                    filename = md_file.stem
                    source_url = site_url or f"https://{site_dir.name.replace('_', '.')}/"

                    meta_file = md_file.with_suffix(".metadata.json")
                    title = f"{filename} ({lang.upper()})"
                    if meta_file.exists():
                        try:
                            mdata = json.loads(meta_file.read_text(encoding="utf-8"))
                            source_url = mdata.get("url") or mdata.get("source_url") or source_url
                            title = mdata.get("title") or title
                        except Exception:
                            pass
                    else:
                        # Fall back to the site's index.json for per-page URLs.
                        page_url = site_url_map.get((lang.lower(), _normalize_title(filename)))
                        if page_url:
                            source_url = page_url

                    if source_url in existing_url_map or source_url in deleted_urls:
                        continue

                    target = docs_dir / md_file.name
                    if target.exists():
                        target = docs_dir / f"{Path(filename).stem}_{uuid.uuid4().hex[:4]}.md"
                    content = f"# {title}\n\nSource: {source_url}\n\n{text}"
                    target.write_text(content, encoding="utf-8")
                    existing_url_map[source_url] = target.name
                    saved_files.append({"url": source_url, "file": target.name, "title": title})
                except Exception:
                    pass

            # Also sync downloaded PDFs found during crawl (original extension).
            pdfs_dir = site_dir / "pdfs"
            if pdfs_dir.exists():
                for pdf_file in pdfs_dir.glob("*.pdf"):
                    try:
                        if f"file:{pdf_file.name}" in deleted_urls:
                            continue
                        target_pdf = docs_dir / pdf_file.name
                        if not target_pdf.exists():
                            shutil.copy(pdf_file, target_pdf)
                            saved_files.append({"url": pdf_file.name, "file": pdf_file.name, "title": pdf_file.stem})
                    except Exception:
                        pass

            # Also sync JSON catalog files from the crawl (original extension).
            for json_file in site_dir.glob("*.json"):
                try:
                    if f"file:{json_file.name}" in deleted_urls:
                        continue
                    target_json = docs_dir / json_file.name
                    if not target_json.exists():
                        shutil.copy(json_file, target_json)
                        saved_files.append({"url": json_file.name, "file": json_file.name, "title": json_file.stem})
                except Exception:
                    pass

    return saved_files


def _list_documents_from_db(db_path: Path, tenant_id: str) -> list[dict]:
    """List a tenant's documents from DB (ingested) merged with disk documents (pending ingestion).

    Shapes rows to what the admin/client documents panels already expect:
    ``name``, ``source``, ``source_url``, ``ingested_at``, ``chunks``,
    ``ingested``, ``size_bytes``, ``extension``.
    """
    _sync_crawl_outputs_to_tenant(tenant_id)
    db_docs = {}
    if db_path.exists():
        try:
            with _tenant_connection(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT d.document_id, d.name, d.source, d.source_url, d.ingested_at,
                           (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.document_id) AS chunk_count
                    FROM documents d
                    WHERE d.tenant_id = ?
                    ORDER BY d.ingested_at DESC
                    """,
                    (tenant_id,),
                ).fetchall()
                for r in rows:
                    db_docs[r["name"]] = {
                        "name": r["name"],
                        "source": r["source"] or "upload",
                        "source_url": r["source_url"],
                        "ingested_at": r["ingested_at"],
                        "chunks": r["chunk_count"] or 0,
                        "ingested": True,
                        "size_bytes": None,
                        "extension": Path(r["name"]).suffix.lstrip("."),
                        "_sort_ts": _ts_to_epoch(r["ingested_at"]),
                    }
        except Exception:
            pass

    docs_dir = TENANTS_DIR / tenant_id / "documents"
    pending_docs = []
    if docs_dir.exists():
        for f in sorted(docs_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file():
                if f.name in db_docs:
                    try:
                        db_docs[f.name]["size_bytes"] = f.stat().st_size
                    except Exception:
                        pass
                else:
                    src_url = None
                    is_scrape = _is_scraped_document_name(f.name)
                    if not is_scrape:
                        src_url = _scraped_source_url(f)
                        is_scrape = bool(src_url)
                    source_type = "scrape" if is_scrape else "upload"
                    try:
                        sz = f.stat().st_size
                    except Exception:
                        sz = 0
                    pending_docs.append({
                        "name": f.name,
                        "source": source_type,
                        "source_url": src_url,
                        "ingested_at": None,
                        "chunks": 0,
                        "ingested": False,
                        "size_bytes": sz,
                        "extension": f.suffix.lstrip("."),
                        "_sort_ts": f.stat().st_mtime,
                    })

    items = list(db_docs.values()) + pending_docs
    items.sort(key=lambda d: d.get("_sort_ts") or 0, reverse=True)
    for d in items:
        d.pop("_sort_ts", None)
    return items



@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TenBit RAG server starting")
    if redis_client.enabled:
        restored = redis_client.shgetall("ingestion_status") or {}
        for tid, raw in restored.items():
            try:
                ingestion_status[tid] = json.loads(raw)
            except Exception:
                pass
        log.info("Restored %d ingestion statuses from Redis", len(restored))
    yield
    log.info("TenBit RAG server shutting down")
    await redis_client.close()
    for engine in _engine_cache.values():
        if hasattr(engine, 'vector_store') and engine.vector_store._client:
            await engine.vector_store.close()


app = FastAPI(title="TenBit Enterprise RAG Multi-Tenant Platform", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(MetricsMiddleware)

spa_dir = Path(os.getenv("RAG_SPA_DIR", str(Path(__file__).parent.parent.parent.parent / "chic-interface-design" / "dist-spa"))).resolve()
if not spa_dir.exists():
    spa_dir = Path(__file__).parent / "static"
    spa_dir.mkdir(parents=True, exist_ok=True)
assets_dir = spa_dir / "assets"
app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets") if assets_dir.exists() else None


# --- Rate Limiting ---

async def _check_rate_limit(client_ip: str, rpm: int = 60):
    key = f"rate_limit:{client_ip}"
    allowed = await redis_client.asliding_window(key, rpm, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


# --- Admin Auth ---

def _get_admin_jwt_secret() -> str:
    return os.getenv("RAG_ADMIN_JWT_SECRET", "")

def _get_admin_password() -> str:
    return os.getenv("RAG_ADMIN_PASSWORD", "admin")

async def require_admin(authorization: str | None = Header(None)):
    secret = _get_admin_jwt_secret()
    if not secret:
        return {"role": "admin", "tenant_id": "admin"}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    payload = verify_jwt(authorization[7:], secret)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


class AdminLoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v1/admin/login")
async def admin_login(req: AdminLoginRequest):
    secret = _get_admin_jwt_secret()
    if not secret:
        return {"status": "error", "detail": "Admin auth not configured (set RAG_ADMIN_JWT_SECRET)"}
    admin_password = _get_admin_password()
    if req.username != "admin" or req.password != admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = generate_jwt("admin", secret)
    return {
        "status": "success",
        "token": token,
        "access_token": token,
        "token_type": "Bearer",
    }



LLM_PROVIDERS = [
    {"id": "gemini", "name": "Google Gemini Cloud", "defaultBaseUrl": "https://generativelanguage.googleapis.com/v1beta", "models": ["gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]},
    {"id": "mistral", "name": "Mistral Cloud", "defaultBaseUrl": "https://api.mistral.ai/v1", "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "open-mistral-nemo"]},
    {"id": "openai", "name": "OpenAI", "defaultBaseUrl": "https://api.openai.com/v1", "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]},
    {"id": "nvidia", "name": "NVIDIA", "defaultBaseUrl": "https://integrate.api.nvidia.com/v1", "models": ["meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct", "mistralai/mistral-7b-instruct-v03"]},
    {"id": "openrouter", "name": "OpenRouter", "defaultBaseUrl": "https://openrouter.ai/api/v1", "models": ["openai/gpt-4o-mini", "openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-8b-instruct"]},
    {"id": "anthropic", "name": "Anthropic", "defaultBaseUrl": "https://api.anthropic.com/v1", "models": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-3-opus-latest"]},
    {"id": "openai_compatible", "name": "OpenAI Compatible", "defaultBaseUrl": "http://localhost:11434/v1", "models": ["gpt-4o-mini"]},
]

EMBEDDING_PROVIDERS = [
    {"id": "hash", "name": "Local Deterministic Hash (384d)", "defaultBaseUrl": None, "models": ["hash-384"], "defaultDimensions": 384},
    {"id": "bge", "name": "BGE Small (Local)", "defaultBaseUrl": None, "models": ["BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5", "BAAI/bge-large-en-v1.5"], "defaultDimensions": 384},
    {"id": "openai", "name": "OpenAI Embeddings", "defaultBaseUrl": "https://api.openai.com/v1", "models": ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"], "defaultDimensions": 1536},
    {"id": "gemini", "name": "Google Gemini Embeddings", "defaultBaseUrl": "https://generativelanguage.googleapis.com/v1beta", "models": ["text-embedding-004", "embedding-001"], "defaultDimensions": 768},
    {"id": "mistral", "name": "Mistral Embeddings", "defaultBaseUrl": "https://api.mistral.ai/v1", "models": ["mistral-embed"], "defaultDimensions": 1024},
]


@app.get("/api/v1/admin/providers")
def get_providers(_admin=Depends(require_admin)):
    return LLM_PROVIDERS


@app.put("/api/v1/admin/providers")
def update_providers(providers: list[dict], _admin=Depends(require_admin)):
    global LLM_PROVIDERS
    LLM_PROVIDERS = providers
    return {"status": "success", "providers": providers}


# --- Pydantic models ---
class TenantOnboardRequest(BaseModel):
    tenant_id: str = Field(..., pattern=r"^[a-zA-Z0-9 _-]+$")  # slug: letters, digits, spaces, hyphens, underscores
    name: str
    subscription_tier: str = "basic"
    monthly_fee: float = 299.00
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    retrieval_top_k: int = 20
    retrieval_rerank_top_k: int = 8
    retrieval_final_context_k: int = 5
    retrieval_dense_weight: float = 0.55
    retrieval_sparse_weight: float = 0.45
    chunking_max_tokens: int = 320
    chunking_overlap_tokens: int = 48
    chunking_semantic: bool = False
    chunking_semantic_threshold: float = 0.75
    reranker_type: str = "local"
    session_memory_limit: int = 8
    chat_retention_days: int = 30
    system_prompt: str | None = None


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    subscription_tier: str | None = None
    monthly_fee: float | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    retrieval_top_k: int | None = None
    retrieval_rerank_top_k: int | None = None
    retrieval_final_context_k: int | None = None
    retrieval_dense_weight: float | None = None
    retrieval_sparse_weight: float | None = None
    chunking_max_tokens: int | None = None
    chunking_overlap_tokens: int | None = None
    chunking_semantic: bool | None = None
    chunking_semantic_threshold: float | None = None
    reranker_type: str | None = None
    session_memory_limit: int | None = None
    chat_retention_days: int | None = None
    system_prompt: str | None = None


class ChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    user_id: str = "web-user"
    filters: dict[str, str] | None = None
    system_prompt: str | None = None


class CloudSyncRequest(BaseModel):
    provider: str = "google_drive"
    cloud_url_or_id: str
    api_key_or_token: str | None = None
    custom_filename: str | None = None
    auto_ingest: bool = True


class ScrapeRequest(BaseModel):
    url: str
    crawl: bool = False
    max_pages: int = 10
    max_depth: int = 2
    full_site: bool = False


class TerminalExecRequest(BaseModel):
    command: str
    tenant_id: str | None = None


# --- Helpers ---

ALLOWED_SCRAPE_SCHEMES = frozenset({"http", "https"})
BLOCKED_SCRAPE_HOSTS = frozenset({
    "127.0.0.1", "localhost", "0.0.0.0", "::1",
    "169.254.169.254",  # AWS/GCP metadata
    "metadata.google.internal",
})


def _validate_scrape_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCRAPE_SCHEMES:
        raise HTTPException(status_code=400, detail=f"Invalid URL scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if host in BLOCKED_SCRAPE_HOSTS:
        raise HTTPException(status_code=400, detail="URL points to internal/blocked host")
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        try:
            first_octet = int(host.split(".")[0])
            if first_octet == 10 or first_octet == 192 or (first_octet == 172 and 16 <= int(host.split(".")[1]) <= 31):
                raise HTTPException(status_code=400, detail="URL points to private network")
        except (ValueError, IndexError):
            pass
    return url


SAFE_EXTENSIONS = frozenset({
    ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".json", ".xml", ".html", ".htm", ".png", ".jpg", ".jpeg", ".gif",
    ".bmp", ".tiff", ".tif", ".webp", ".svg", ".epub", ".rtf",
})
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


def _validate_upload_file(filename: str, file_size: int) -> None:
    ext = Path(filename).suffix.lower()
    if not ext:
        raise HTTPException(status_code=400, detail="File must have an extension")
    if ext not in SAFE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    if file_size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE // 1024 // 1024} MB)")


def _resolve_tenant_document_path(tenant_id: str, filename: str, docs_dir: Path | None = None) -> Path:
    if not filename or not isinstance(filename, str):
        raise ValueError("Invalid filename")
    candidate = Path(filename).name
    if not candidate or candidate in {".", ".."} or candidate != filename:
        raise ValueError("Invalid filename")
    base_dir = docs_dir or (TENANTS_DIR / tenant_id / "documents")
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / candidate


def _is_scraped_document_name(name: str) -> bool:
    normalized = str(name).lower()
    return normalized.startswith("scraped_") or normalized.startswith("_scraped_") or normalized.startswith("scrape_")


def _get_scraper_service() -> ScraperService:
    global _scraper_service
    if _scraper_service is None:
        _scraper_service = ScraperService()
    return _scraper_service


def _get_tenant_config(tenant: dict) -> AppConfig:
    return AppConfig(
        tenant_id=tenant["tenant_id"],
        default_kb="default",
        session_memory_limit=tenant.get("session_memory_limit", 8),
        chat_retention_days=tenant.get("chat_retention_days", 30),
        storage=StorageConfig(provider="sqlite", path=str(_tenant_db_path(tenant["tenant_id"], tenant))),
        embeddings=EmbeddingConfig(
            provider=tenant["embedding_provider"], model=tenant["embedding_model"],
            dimensions=tenant["embedding_dimensions"], base_url=tenant.get("embedding_base_url"),
            api_key=tenant.get("embedding_api_key"),
        ),
        retrieval=RetrievalConfig(
            top_k=tenant["retrieval_top_k"], rerank_top_k=tenant["retrieval_rerank_top_k"],
            final_context_k=tenant["retrieval_final_context_k"],
            dense_weight=tenant["retrieval_dense_weight"], sparse_weight=tenant["retrieval_sparse_weight"],
            reranker=tenant.get("reranker_type", "local"),
        ),
        chunking=ChunkingConfig(
            max_tokens=tenant["chunking_max_tokens"], overlap_tokens=tenant["chunking_overlap_tokens"],
            semantic_chunking=tenant.get("chunking_semantic", True),
            semantic_similarity_threshold=tenant.get("chunking_semantic_threshold", 0.75),
        ),
        system_prompt=tenant.get("system_prompt"),
        llm=LLMSettings(
            provider=tenant["llm_provider"], api_key=tenant["llm_api_key"],
            model=tenant["llm_model"], base_url=tenant["llm_base_url"],
        ),
        qdrant=QdrantConfig(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
        ),
        rate_limit=RateLimitConfig(enabled=True, requests_per_minute=60),
        security=SecurityConfig(encrypt_keys=False, admin_auth_enabled=False),
        observability=ObservabilityConfig(health_endpoint=True, structured_logging=True),
    )


def _get_engine(tenant: dict) -> RagEngine:
    tid = tenant["tenant_id"]
    if tid not in _engine_cache:
        config = _get_tenant_config(tenant)
        engine = RagEngine(config, root=ROOT_DIR)
        _engine_cache[tid] = engine
    return _engine_cache[tid]


async def _ensure_engine_initialized(engine: RagEngine):
    if not engine._initialized:
        await engine.initialize()


def _sync_ingestion_to_redis(tenant_id: str):
    if tenant_id in ingestion_status:
        redis_client.sset_json(f"ingestion:{tenant_id}", ingestion_status[tenant_id], ttl=3600)

def _log_to_ingestion(tenant_id: str, message: str, progress: int | None = None):
    if tenant_id not in ingestion_status:
        ingestion_status[tenant_id] = {"status": "idle", "logs": [], "progress": 0, "summary": None}
    ingestion_status[tenant_id]["logs"].append(message)
    if progress is not None:
        ingestion_status[tenant_id]["progress"] = progress
    _sync_ingestion_to_redis(tenant_id)


def _run_ingestion_background(tenant_id: str, tenant_data: dict, apply_ocr: bool = False):
    try:
        _log_to_ingestion(tenant_id, "Starting Ingestion Pipeline...", 5)
        tenant_dir = TENANTS_DIR / tenant_id
        docs_dir = tenant_dir / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)

        config = _get_tenant_config(tenant_data)
        engine = _get_engine(tenant_data)

        _log_to_ingestion(tenant_id, "Syncing database with documents directory...", 15)
        files = list(docs_dir.glob("*"))
        file_ids = set()
        for f in files:
            if f.is_file():
                file_ids.add(_document_id(f))

        # Build set of already-ingested document IDs to skip duplicates
        already_ingested_ids = set()
        db_path = Path(config.storage.path)
        if db_path.exists():
            try:
                with _tenant_connection(db_path) as conn:
                    rows = conn.execute("SELECT document_id FROM documents").fetchall()
                    already_ingested_ids = {r[0] for r in rows}
            except Exception:
                pass

        _log_to_ingestion(tenant_id, f"Found {len(files)} files ({len(already_ingested_ids)} already ingested).", 25)
        if not files:
            _log_to_ingestion(tenant_id, "No documents found. Index is clean.", 100)
            ingestion_status[tenant_id]["status"] = "completed"
            ingestion_status[tenant_id]["summary"] = {"documents": 0, "chunks": 0}
            _sync_ingestion_to_redis(tenant_id)
            return

        total_docs = 0
        total_chunks = 0
        skipped_docs = 0
        errors = []

        for idx, file_path in enumerate(files):
            if not file_path.is_file():
                continue
            progress_pct = int(25 + (idx / len(files)) * 70)

            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                skipped_docs += 1
                _log_to_ingestion(tenant_id, f"[Skip] {file_path.name}: unsupported type '{ext or '[no-ext]'}'.", progress_pct)
                continue

            doc_id = _document_id(file_path)
            if doc_id in already_ingested_ids:
                _log_to_ingestion(tenant_id, f"[Skip] {file_path.name} already ingested.", progress_pct)
                skipped_docs += 1
                continue

            try:
                _log_to_ingestion(tenant_id, f"[Step 2] Extracting text from {file_path.name} ({idx+1}/{len(files)})...", progress_pct)
                document = load_document(file_path, use_ocr=apply_ocr)
                char_count = len(document.text.strip())
                if char_count == 0:
                    _log_to_ingestion(tenant_id, f"  [Warning] {file_path.name}: no text extracted, skipping.", progress_pct)
                    continue
                _log_to_ingestion(tenant_id, f"  [OK] {file_path.name}: extracted {char_count} chars.", progress_pct)

                _log_to_ingestion(tenant_id, f"[Step 3] Chunking {file_path.name}...", progress_pct)
                chunks = engine.chunker.chunk(document, tenant_id=engine.config.tenant_id, knowledge_base_id="default")
                _log_to_ingestion(tenant_id, f"  [OK] {file_path.name}: chunked into {len(chunks)} chunks.", progress_pct)

                _log_to_ingestion(tenant_id, f"[Step 4] Embedding {len(chunks)} chunks of {file_path.name}...", progress_pct)
                embeddings = engine.embedding_provider.embed([chunk.text for chunk in chunks])
                for chunk, embedding in zip(chunks, embeddings):
                    chunk.embedding = embedding

                _log_to_ingestion(tenant_id, f"[Step 5] Upserting {file_path.name} to storage...", progress_pct)
                source = "scrape" if _is_scraped_document_name(file_path.name) else "upload"
                source_url = document.metadata.get("source_url") if hasattr(document, "metadata") else None
                document.metadata["tenant_id"] = engine.config.tenant_id
                engine.store.upsert_document(document, engine.config.tenant_id, "default", source=source, source_url=source_url)
                engine.store.upsert_chunks(chunks)

                total_docs += 1
                total_chunks += len(chunks)
            except Exception as e:
                tb = traceback.format_exc()
                err_msg = f"{file_path.name}: {e}"
                errors.append(err_msg)
                _log_to_ingestion(tenant_id, f"  [Error] {err_msg}", progress_pct)
                _log_to_ingestion(tenant_id, f"  [Traceback]\n{tb}", progress_pct)

        DOCUMENTS_INGESTED.labels(tenant_id=tenant_id).inc(total_docs)
        CHUNKS_CREATED.labels(tenant_id=tenant_id).inc(total_chunks)
        _log_to_ingestion(tenant_id, "Finalizing...", 95)
        status_str = "completed" if not errors else "error"
        _log_to_ingestion(tenant_id, f"Ingestion finished! New: {total_docs} docs, {total_chunks} chunks. Skipped: {skipped_docs}. Errors: {len(errors)}", 100)
        ingestion_status[tenant_id]["status"] = status_str
        ingestion_status[tenant_id]["summary"] = {"documents": total_docs, "chunks": total_chunks, "skipped": skipped_docs, "errors": errors}
        _sync_ingestion_to_redis(tenant_id)
        admin_store.log_activity(tenant_id=tenant_id, level="WARNING" if errors else "INFO", operation="INGESTION",
                                message=f"Ingestion {'completed with errors' if errors else 'successful'}: {total_docs} new docs, {total_chunks} chunks, {skipped_docs} skipped.",
                                details={"documents": total_docs, "chunks": total_chunks, "skipped": skipped_docs, "errors": errors})
    except Exception as exc:
        trace = traceback.format_exc()
        _log_to_ingestion(tenant_id, f"[Fatal] {exc}\n{trace}", 100)
        ingestion_status[tenant_id]["status"] = "error"
        ingestion_status[tenant_id]["summary"] = {"error": str(exc)}
        _sync_ingestion_to_redis(tenant_id)
        admin_store.log_activity(tenant_id=tenant_id, level="ERROR", operation="INGESTION", message=f"Fatal ingestion error: {exc}", traceback=trace)


# --- SPA serving ---

_shared_index_html: str | None = None

def _get_spa_index() -> str | None:
    global _shared_index_html
    if _shared_index_html is not None:
        return _shared_index_html
    idx = spa_dir / "index.html"
    if idx.exists():
        _shared_index_html = idx.read_text(encoding="utf-8")
        return _shared_index_html
    return None


def _spa_response(cache_control: str = "no-store") -> HTMLResponse:
    html = _get_spa_index()
    if html is None:
        return HTMLResponse(content="<h3>Frontend is still generating. Reload in a few seconds...</h3>")
    resp = HTMLResponse(content=html)
    resp.headers["Cache-Control"] = cache_control
    return resp


@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    return _spa_response()


@app.get("/client", response_class=HTMLResponse)
def get_client_dashboard():
    return _spa_response()


@app.get("/widget", response_class=HTMLResponse)
def get_chat_widget():
    return _spa_response()


@app.get("/login", response_class=HTMLResponse)
def get_login():
    return _spa_response()


@app.get("/admin", response_class=HTMLResponse)
def get_admin_spa():
    return _spa_response()


# --- Health & Monitoring ---

@app.get("/api/v1/health")
async def health_check():
    from dataclasses import asdict
    from rbs_rag.models import HealthStatus
    qdrant_status = "disconnected"
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = os.getenv("QDRANT_PORT", "6333")
        c = QdrantClient(f"http://{qdrant_host}:{qdrant_port}")
        c.get_collections()
        qdrant_status = "connected"
    except Exception:
        pass
    db_ok = ADMIN_DB_PATH.exists()
    return asdict(HealthStatus(
        status="ok" if db_ok else "degraded",
        db="connected" if db_ok else "not_found",
        qdrant=qdrant_status,
        uptime_seconds=round(time.time() - _server_start_time, 2),
    ))


@app.get("/metrics")
async def metrics():
    return metrics_export()


@app.get("/api/v1/system/status")
async def system_status(_admin=Depends(require_admin)):
    tenants = admin_store.list_tenants()
    total_docs = 0
    total_chunks = 0
    for t in tenants:
        db_path = _tenant_db_path(t["tenant_id"], t)
        if db_path.exists():
            try:
                with _tenant_connection(db_path) as conn:
                    row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
                    if row:
                        total_docs += row[0]
                    row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                    if row:
                        total_chunks += row[0]
            except Exception:
                pass
    ACTIVE_TENANTS.set(len(tenants))
    ENGINE_UPTIME.set(round(time.time() - _server_start_time, 2))
    return {
        "uptime_seconds": round(time.time() - _server_start_time, 2),
        "tenants": len(tenants),
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "version": "1.0.0",
    }


# --- ADMIN APIs ---

@app.get("/api/v1/tenants")
def get_tenants(_admin=Depends(require_admin)):
    tenants = admin_store.list_tenants()
    for t in tenants:
        t["llm_api_key"] = "***"
        if "embedding_api_key" in t and t["embedding_api_key"]:
            t["embedding_api_key"] = "***"
        db_path = _tenant_db_path(t["tenant_id"], t)
        doc_count = 0
        chunk_count = 0
        if db_path.exists():
            try:
                with _tenant_connection(db_path) as conn:
                    row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
                    doc_count = row[0] if row else 0
                    row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                    chunk_count = row[0] if row else 0
            except Exception:
                pass
        t["doc_count"] = doc_count
        t["chunk_count"] = chunk_count
    return tenants


@app.post("/api/v1/tenants")
def onboard_tenant(req: TenantOnboardRequest, _admin=Depends(require_admin)):
    existing = admin_store.get_tenant(req.tenant_id)
    if existing:
        raise HTTPException(status_code=400, detail="Tenant ID already exists.")
    api_key = f"rbs_rag_sk_{uuid.uuid4().hex}"
    tenant_data = req.model_dump()
    tenant_data["api_key"] = api_key
    tenant_data["status"] = "active"
    provision_tenant(admin_store, tenant_data, ROOT_DIR)
    tenant_dir = TENANTS_DIR / req.tenant_id
    (tenant_dir / "documents").mkdir(parents=True, exist_ok=True)
    ingestion_status[req.tenant_id] = {"status": "idle", "logs": ["Tenant created."], "progress": 0, "summary": None}
    _sync_ingestion_to_redis(req.tenant_id)
    return {"status": "success", "tenant_id": req.tenant_id, "api_key": api_key}


@app.get("/api/v1/tenants/{tenant_id}")
def get_tenant_details(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant["llm_api_key"] = "***"
    if "embedding_api_key" in tenant and tenant["embedding_api_key"]:
        tenant["embedding_api_key"] = "***"
    return tenant


@app.get("/api/v1/tenants/{tenant_id}/config")
def get_tenant_config(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    def _mask(v):
        return "***" if v else None
    return {
        "name": tenant["name"],
        "status": tenant["status"],
        "subscriptionTier": tenant.get("subscription_tier", "basic"),
        "monthlyFee": tenant.get("monthly_fee", 299.0),
        "llmProvider": tenant["llm_provider"],
        "llmModel": tenant["llm_model"],
        "llmApiKey": _mask(tenant.get("llm_api_key")),
        "llmBaseUrl": tenant.get("llm_base_url"),
        "embeddingProvider": tenant["embedding_provider"],
        "embeddingModel": tenant["embedding_model"],
        "embeddingDimensions": tenant["embedding_dimensions"],
        "embeddingBaseUrl": tenant.get("embedding_base_url"),
        "embeddingApiKey": _mask(tenant.get("embedding_api_key")),
        "retrievalTopK": tenant["retrieval_top_k"],
        "retrievalRerankTopK": tenant["retrieval_rerank_top_k"],
        "retrievalFinalContextK": tenant["retrieval_final_context_k"],
        "retrievalDenseWeight": tenant["retrieval_dense_weight"],
        "retrievalSparseWeight": tenant["retrieval_sparse_weight"],
        "chunkingMaxTokens": tenant["chunking_max_tokens"],
        "chunkingOverlapTokens": tenant["chunking_overlap_tokens"],
        "chunkingSemantic": bool(tenant.get("chunking_semantic", 0)),
        "chunkingSemanticThreshold": tenant.get("chunking_semantic_threshold", 0.75),
        "rerankerType": tenant.get("reranker_type", "local"),
        "sessionMemoryLimit": tenant.get("session_memory_limit", 8),
        "chatRetentionDays": tenant.get("chat_retention_days", 30),
        "systemPrompt": tenant.get("system_prompt"),
    }


@app.put("/api/v1/tenants/{tenant_id}")
def update_tenant(tenant_id: str, req: TenantUpdateRequest, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    updated_data = dict(tenant)
    for field, value in req.model_dump(exclude_none=True).items():
        if value != "***":
            updated_data[field] = value
    updated_data["tenant_id"] = tenant_id
    updated_data["api_key"] = tenant["api_key"]
    updated_data["db_path"] = tenant.get("db_path") or f"tenants/{tenant_id}/rag.db"
    admin_store.upsert_tenant(updated_data)
    if tenant_id in _engine_cache:
        del _engine_cache[tenant_id]
    return {"status": "success"}


@app.delete("/api/v1/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 1. Pop & close any cached engine for tenant
    engine = _engine_cache.pop(tenant_id, None)
    if engine:
        try:
            if hasattr(engine.store, "close"):
                engine.store.close()
        except Exception:
            pass

    # 2. Delete tenant record from admin_store DB
    admin_store.delete_tenant(tenant_id)

    # 3. Remove DB file & directory safely
    db_path = _tenant_db_path(tenant_id, tenant)
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass

    tenant_dir = TENANTS_DIR / tenant_id
    if tenant_dir.exists():
        try:
            shutil.rmtree(tenant_dir, ignore_errors=True)
        except Exception as e:
            log.warning("Failed to remove tenant dir %s: %s", tenant_dir, e)

    ingestion_status.pop(tenant_id, None)
    try:
        redis_client.sdelete(f"ingestion:{tenant_id}")
    except Exception:
        pass

    return {"status": "success"}


# --- TENANT DOCUMENTS APIs ---

@app.get("/api/v1/tenants/{tenant_id}/documents")
def list_tenant_documents(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    db_path = _tenant_db_path(tenant_id, tenant)
    return _list_documents_from_db(db_path, tenant_id)


@app.get("/api/v1/tenants/{tenant_id}/documents/{filename}/chunks")
def get_document_chunks(tenant_id: str, filename: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    db_path = _tenant_db_path(tenant_id, tenant)
    if not db_path.exists():
        return []
    try:
        with _tenant_connection(db_path) as conn:
            conn.row_factory = sqlite3.Row
            doc = conn.execute("SELECT document_id FROM documents WHERE name = ? AND tenant_id = ?", (filename, tenant_id)).fetchone()
            if not doc:
                return []
            rows = conn.execute("SELECT chunk_id, ordinal, text, metadata_json FROM chunks WHERE document_id = ? ORDER BY ordinal", (doc["document_id"],)).fetchall()
            return [{"chunk_id": r["chunk_id"], "ordinal": r["ordinal"], "text": r["text"], "metadata": json.loads(r["metadata_json"])} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/documents")
async def upload_tenant_documents(tenant_id: str, files: list[UploadFile] = File(...), apply_ocr: bool = Query(default=False), _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    uploaded_files = []
    for file in files:
        filename = Path(file.filename).name
        _validate_upload_file(filename, 0)
        ext = Path(filename).suffix.lower()
        safe_name = f"{uuid.uuid4().hex}{ext}"
        target_path = docs_dir / safe_name
        content = file.file.read()
        _validate_upload_file(filename, len(content))
        with target_path.open("wb") as buffer:
            buffer.write(content)
        uploaded_files.append({"original": filename, "saved_as": safe_name})
    return {"status": "success", "uploaded": uploaded_files}


@app.delete("/api/v1/tenants/{tenant_id}/documents/{filename}")
def delete_tenant_document(tenant_id: str, filename: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        file_path = _resolve_tenant_document_path(tenant_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    source_url = _scraped_source_url(file_path) if file_path.exists() else None
    if file_path.exists():
        file_path.unlink()
    _purge_crawl_output_for_file(source_url, filename)
    _mark_deleted_source(tenant_id, source_url, filename)
    db_path = _tenant_db_path(tenant_id, tenant)
    if db_path.exists():
        try:
            with _tenant_connection(db_path) as conn:
                row = conn.execute(
                    "SELECT document_id FROM documents WHERE tenant_id = ? AND name = ?",
                    (tenant_id, filename),
                ).fetchone()
                doc_id = row["document_id"] if row else _document_id(file_path)
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                conn.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database sync error: {e}")
    return {"status": "success"}


@app.patch("/api/v1/tenants/{tenant_id}/documents/{filename}")
def rename_tenant_document(tenant_id: str, filename: str, req: dict = Body(...), _admin=Depends(require_admin)):
    """Rename a pending (not yet ingested) document file on disk.
    Body: { \"new_name\": \"friendly-name.txt\" }"""
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    new_name = req.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name is required")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    try:
        safe = _resolve_tenant_document_path(tenant_id, new_name, docs_dir).name
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        old_path = _resolve_tenant_document_path(tenant_id, filename, docs_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_path = docs_dir / safe
    if not old_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    if new_path.exists() and new_path != old_path:
        raise HTTPException(status_code=409, detail="A file with that name already exists")
    old_path.rename(new_path)
    return {"status": "success", "old_name": filename, "new_name": safe}


def _resolve_duplicate_actions(tenant_id: str, actions: list[dict]) -> list[dict]:
    """Resolve staged duplicate files. Each action item:
    {existing_file, new_file, action: remove|keep_both|rename|replace, new_name?}
    new_file refers to a file staged in <docs>/.pending/.
    """
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    pending_dir = docs_dir / _PENDING_DIR
    results = []
    for action_item in actions:
        existing_file = Path(action_item.get("existing_file", "")).name
        new_file = Path(action_item.get("new_file", "")).name
        action = action_item.get("action", "remove")
        pending_path = pending_dir / new_file
        existing_path = docs_dir / existing_file
        try:
            if action == "remove":
                if pending_path.exists():
                    pending_path.unlink()
                results.append({"file": new_file, "action": "removed", "kept": existing_file})
            elif action == "replace":
                if existing_path.exists():
                    existing_path.unlink()
                if pending_path.exists():
                    pending_path.rename(docs_dir / existing_file)
                results.append({"file": new_file, "action": "replaced", "kept": existing_file})
            elif action == "rename":
                new_name = Path(action_item.get("new_name", "")).name.strip()
                if not new_name or "/" in new_name or "\\" in new_name:
                    results.append({"file": new_file, "action": "error", "error": "new_name is required"})
                elif pending_path.exists():
                    target = _friendly_unique_name(docs_dir, new_name)
                    pending_path.rename(docs_dir / target)
                    results.append({"file": new_file, "action": "renamed", "kept": target})
                else:
                    results.append({"file": new_file, "action": "error", "error": "pending file not found"})
            else:  # keep_both
                if pending_path.exists():
                    target = _friendly_unique_name(docs_dir, new_file)
                    pending_path.rename(docs_dir / target)
                    results.append({"file": new_file, "action": "kept_both", "kept": target})
                else:
                    results.append({"file": new_file, "action": "error", "error": "pending file not found"})
        except Exception as e:
            results.append({"file": new_file, "action": "error", "error": str(e)})
    return results


@app.post("/api/v1/tenants/{tenant_id}/documents/resolve-duplicates")
def resolve_duplicates(tenant_id: str, req: dict = Body(...), _admin=Depends(require_admin)):
    """Resolve duplicate files staged from scraping.
    Body: { \"actions\": [{\"existing_file\": \"...\", \"new_file\": \"...\", \"action\": \"remove\"|\"keep_both\"|\"rename\"|\"replace\", \"new_name\": \"...\"}] }
    - remove:    delete the staged copy (keep existing)
    - keep_both: move the staged copy into documents (auto ' (2)' suffix if needed)
    - rename:    move the staged copy into documents under new_name
    - replace:   delete existing, move staged copy to the existing name
    """
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    actions = req.get("actions", [])
    return {"status": "success", "results": _resolve_duplicate_actions(tenant_id, actions)}


# --- INGESTION APIs ---

@app.post("/api/v1/tenants/{tenant_id}/ingest")
def trigger_ingestion(tenant_id: str, background_tasks: BackgroundTasks, apply_ocr: bool = Query(default=False), _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant_id in ingestion_status and ingestion_status[tenant_id]["status"] == "running":
        return {"status": "already_running"}
    ingestion_status[tenant_id] = {"status": "running", "logs": ["[System] Initiating ingestion."], "progress": 0, "summary": None}
    redis_client.sset_json(f"ingestion:{tenant_id}", ingestion_status[tenant_id], ttl=3600)
    background_tasks.add_task(_run_ingestion_background, tenant_id, tenant, apply_ocr)
    already_ingested = 0
    db_path = _tenant_db_path(tenant_id, tenant)
    if db_path.exists():
        try:
            with _tenant_connection(db_path) as conn:
                already_ingested = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        except Exception:
            pass
    return {"status": "started", "apply_ocr": apply_ocr, "already_ingested": already_ingested}


@app.get("/api/v1/tenants/{tenant_id}/ingest/status")
def get_ingestion_status(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    status = ingestion_status.get(tenant_id)
    if status is None and redis_client.enabled:
        raw = redis_client.sget_json(f"ingestion:{tenant_id}")
        if raw:
            ingestion_status[tenant_id] = raw
            status = raw
    if status is None:
        status = {"status": "idle", "logs": ["No ingestion tasks run yet."], "progress": 0, "summary": None}
    return status


# --- CHAT APIs ---

@app.post("/api/v1/tenants/{tenant_id}/chat")
async def chat_playground(tenant_id: str, req: ChatRequest, x_forwarded_for: str = Header("127.0.0.1"), _admin=Depends(require_admin)):
    await _check_rate_limit(x_forwarded_for, 60)
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Tenant account is suspended.")
    injection_flags = detect_prompt_injection(req.query)
    if injection_flags:
        PROMPT_INJECTIONS_BLOCKED.inc()
        admin_store.log_activity(tenant_id=tenant_id, level="WARNING", operation="PROMPT_INJECTION_DETECTED",
                                message=f"Injection patterns: {injection_flags}", details={"query": req.query})
        return {
            "answer": "I cannot process this request as it appears to contain prompt injection attempts.",
            "citations": [],
            "contexts": [],
            "validation": {"sufficient": False, "confidence": "low", "reasons": ["Prompt injection detected"], "confidence_score": 0.0},
            "profile": {},
        }
    engine = _get_engine(tenant)
    try:
        ans = engine.ask(query=req.query, kb="default", session_id=req.session_id, user_id=req.user_id, filters=req.filters, system_prompt=req.system_prompt)
        if ans.contexts:
            CHUNKS_RETRIEVED.observe(len(ans.contexts))
        return {
            "answer": ans.text,
            "citations": [{"index": c.index, "document_name": c.document_name, "section": c.section, "chunk_id": c.chunk_id} for c in ans.citations],
            "contexts": [{"text": ctx.chunk.text, "score": ctx.score, "dense_score": ctx.dense_score, "sparse_score": ctx.sparse_score, "rerank_score": ctx.rerank_score, "metadata": ctx.chunk.metadata} for ctx in ans.contexts],
            "validation": {"sufficient": ans.validation.sufficient, "confidence": ans.validation.confidence, "reasons": ans.validation.reasons, "confidence_score": ans.validation.confidence_score},
            "profile": ans.profile,
        }
    except Exception as e:
        tb_str = traceback.format_exc()
        admin_store.log_activity(tenant_id=tenant_id, level="ERROR", operation="LLM_QUERY", message=str(e), traceback=tb_str, details={"query": req.query, "session_id": req.session_id})
        raise HTTPException(status_code=500, detail=f"Model API Error: {e}")


@app.post("/api/v1/tenants/{tenant_id}/chat/stream")
async def chat_playground_stream(tenant_id: str, req: ChatRequest, x_forwarded_for: str = Header("127.0.0.1"), _admin=Depends(require_admin)):
    await _check_rate_limit(x_forwarded_for, 30)
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Tenant account is suspended.")
    injection_flags = detect_prompt_injection(req.query)
    if injection_flags:
        admin_store.log_activity(tenant_id=tenant_id, level="WARNING", operation="PROMPT_INJECTION_DETECTED",
                                message=f"Injection patterns: {injection_flags}", details={"query": req.query})
        async def rejection_stream():
            yield f"data: {json.dumps({'text': 'Request rejected due to prompt injection.', 'done': True})}\n\n"
        return StreamingResponse(rejection_stream(), media_type="text/event-stream")
    engine = _get_engine(tenant)

    async def event_stream():
        async for chunk in engine.ask_stream(query=req.query, kb="default", session_id=req.session_id, user_id=req.user_id, filters=req.filters, system_prompt=req.system_prompt):
            data = {"text": chunk.text, "done": chunk.done}
            if chunk.error:
                data["error"] = chunk.error
            if chunk.citations:
                data["citations"] = [{"index": c.index, "document_name": c.document_name, "section": c.section, "chunk_id": c.chunk_id} for c in chunk.citations]
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/v1/chat")
async def chat_integration(req: ChatRequest, x_api_key: str = Header(..., alias="X-API-Key"), x_forwarded_for: str = Header("127.0.0.1")):
    await _check_rate_limit(x_forwarded_for, 60)
    tenant = admin_store.get_tenant_by_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Client account is suspended.")
    injection_flags = detect_prompt_injection(req.query)
    if injection_flags:
        PROMPT_INJECTIONS_BLOCKED.inc()
        return {"answer": "Request rejected due to prompt injection.", "citations": [], "validation": {"sufficient": False, "confidence": "low"}}
    engine = _get_engine(tenant)
    try:
        ans = engine.ask(query=req.query, kb="default", session_id=req.session_id, user_id=req.user_id, filters=req.filters, system_prompt=req.system_prompt)
        if ans.contexts:
            CHUNKS_RETRIEVED.observe(len(ans.contexts))
        return {"answer": ans.text, "citations": [{"index": c.index, "document_name": c.document_name, "section": c.section, "chunk_id": c.chunk_id} for c in ans.citations], "validation": {"sufficient": ans.validation.sufficient, "confidence": ans.validation.confidence}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/chat/stream")
async def chat_integration_stream(req: ChatRequest, x_api_key: str = Header(..., alias="X-API-Key"), x_forwarded_for: str = Header("127.0.0.1")):
    await _check_rate_limit(x_forwarded_for, 30)
    tenant = admin_store.get_tenant_by_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Client account is suspended.")
    injection_flags = detect_prompt_injection(req.query)
    if injection_flags:
        async def reject_stream():
            yield f"data: {json.dumps({'text': 'Request rejected due to prompt injection.', 'done': True})}\n\n"
        return StreamingResponse(reject_stream(), media_type="text/event-stream")
    engine = _get_engine(tenant)

    async def event_stream():
        async for chunk in engine.ask_stream(query=req.query, kb="default", session_id=req.session_id, user_id=req.user_id, filters=req.filters, system_prompt=req.system_prompt):
            data = {"text": chunk.text, "done": chunk.done}
            if chunk.error:
                data["error"] = chunk.error
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- CLIENT (API Key) Endpoints ---

def _require_client_api(x_api_key: str = Header(..., alias="X-API-Key")):
    tenant = admin_store.get_tenant_by_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Client account is suspended.")
    return tenant

def _resolve_client_tenant(x_api_key: str | None = Header(None, alias="X-API-Key"), api_key: str | None = Query(None)):
    key = api_key or x_api_key
    if not key:
        raise HTTPException(status_code=401, detail="Missing API Key.")
    tenant = admin_store.get_tenant_by_api_key(key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Client account is suspended.")
    return tenant

@app.get("/api/v1/client/documents")
def client_list_documents(tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    db_path = _tenant_db_path(tenant_id, tenant)
    return _list_documents_from_db(db_path, tenant_id)


@app.post("/api/v1/client/documents/resolve-duplicates")
def client_resolve_duplicates(req: dict = Body(...), tenant=Depends(_resolve_client_tenant)):
    """Client equivalent of resolve-duplicates (staged duplicate files from scraping)."""
    actions = req.get("actions", [])
    return {"status": "success", "results": _resolve_duplicate_actions(tenant["tenant_id"], actions)}


@app.get("/api/v1/client/documents/{filename}/chunks")
def client_get_document_chunks(filename: str, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    db_path = _tenant_db_path(tenant_id, tenant)
    if not db_path.exists():
        return []
    try:
        with _tenant_connection(db_path) as conn:
            doc = conn.execute("SELECT document_id FROM documents WHERE name = ? AND tenant_id = ?", (filename, tenant_id)).fetchone()
            if not doc:
                return []
            rows = conn.execute("SELECT chunk_id, ordinal, text, metadata_json FROM chunks WHERE document_id = ? ORDER BY ordinal", (doc["document_id"],)).fetchall()
            return [{"chunk_id": r["chunk_id"], "ordinal": r["ordinal"], "text": r["text"], "metadata": json.loads(r["metadata_json"])} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tenants/{tenant_id}/documents/{filename}")
def admin_get_document(tenant_id: str, filename: str, _admin=Depends(require_admin)):
    try:
        file_path = _resolve_tenant_document_path(tenant_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    content = file_path.read_bytes()
    media_type = "text/plain"
    ext = file_path.suffix.lower()
    if ext in {".pdf"}:
        media_type = "application/pdf"
    elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        media_type = f"image/{ext.lstrip('.')}"
    elif ext in {".html", ".htm"}:
        media_type = "text/html"
    elif ext in {".docx"}:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"inline; filename=\"{filename}\""})

@app.get("/api/v1/client/documents/{filename}")
def client_get_document(filename: str, x_api_key: str | None = Header(None, alias="X-API-Key"), api_key: str | None = Query(None)):
    key = api_key or x_api_key
    if not key:
        raise HTTPException(status_code=401, detail="Missing API Key. Provide via X-API-Key header or ?api_key= query param.")
    tenant = admin_store.get_tenant_by_api_key(key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API Key.")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="Client account is suspended.")
    tenant_id = tenant["tenant_id"]
    try:
        file_path = _resolve_tenant_document_path(tenant_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    content = file_path.read_bytes()
    media_type = "text/plain"
    ext = file_path.suffix.lower()
    if ext in {".pdf"}:
        media_type = "application/pdf"
    elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        media_type = f"image/{ext.lstrip('.')}"
    elif ext in {".html", ".htm"}:
        media_type = "text/html"
    elif ext in {".docx"}:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"inline; filename=\"{filename}\""})

@app.post("/api/v1/client/documents")
async def client_upload_documents(files: list[UploadFile] = File(...), tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    uploaded_files = []
    for file in files:
        filename = Path(file.filename).name
        _validate_upload_file(filename, 0)
        ext = Path(filename).suffix.lower()
        safe_name = f"{uuid.uuid4().hex}{ext}"
        target_path = docs_dir / safe_name
        content = await file.read()
        _validate_upload_file(filename, len(content))
        with target_path.open("wb") as buffer:
            buffer.write(content)
        uploaded_files.append({"original": filename, "saved_as": safe_name})
    return {"status": "success", "uploaded": uploaded_files}

@app.post("/api/v1/client/ingest")
def client_trigger_ingestion(background_tasks: BackgroundTasks, apply_ocr: bool = Query(default=False), tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    if tenant_id in ingestion_status and ingestion_status[tenant_id]["status"] == "running":
        return {"status": "already_running"}
    ingestion_status[tenant_id] = {"status": "running", "logs": ["[System] Initiating ingestion."], "progress": 0, "summary": None}
    _sync_ingestion_to_redis(tenant_id)
    background_tasks.add_task(_run_ingestion_background, tenant_id, tenant, apply_ocr)
    return {"status": "started", "apply_ocr": apply_ocr}

@app.get("/api/v1/client/ingest/status")
def client_get_ingestion_status(tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    status = ingestion_status.get(tenant_id, {"status": "idle", "logs": ["No ingestion tasks run yet."], "progress": 0, "summary": None})
    return status

@app.post("/api/v1/client/scrape")
async def client_scrape_url(req: ScrapeRequest, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    try:
        if req.crawl:
            job = await scraper.crawl_url(req.url, max_pages=req.max_pages, max_depth=req.max_depth, full_site=req.full_site)
        else:
            job = await scraper.scrape_url(req.url)
        pages = [
            {"text": r.get("text", ""), "metadata": r.get("metadata", {})}
            for r in (job.results or []) if r.get("text")
        ]
        saved_files, duplicates = _save_scraped_pages(tenant_id, pages, req.url)
        if saved_files:
            _save_crawl_output(
                site=_crawl_site_slug(req.url),
                metadata={"strategy": "crawl" if req.crawl else "single", "is_wordpress": False, "languages_found": [], "source_url": req.url},
                pages=[f"# {f['title']}\n\nSource: {f['url']}\n\n" for f in saved_files],
            )
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if saved_files else "WARNING", operation="SCRAPE",
                                message=f"Scraped {req.url}: {len(saved_files)} file(s), {len(duplicates)} duplicate(s)",
                                details={"url": req.url, "files": saved_files, "duplicates": duplicates})
        return {"status": "completed" if saved_files else "failed", "job_id": job.job_id, "url": req.url,
                "files_saved": len(saved_files), "files": saved_files, "duplicates": duplicates, "error": job.error}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {e}")

@app.delete("/api/v1/client/documents/{filename}")
def client_delete_document(filename: str, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    try:
        file_path = _resolve_tenant_document_path(tenant_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    file_existed = file_path.exists()
    source_url = _scraped_source_url(file_path) if file_existed else None
    file_deleted = False
    if file_existed:
        file_path.unlink()
        file_deleted = True
    _purge_crawl_output_for_file(source_url, filename)
    _mark_deleted_source(tenant_id, source_url, filename)
    db_path = _tenant_db_path(tenant_id, tenant)
    deleted = False
    if db_path.exists():
        try:
            with _tenant_connection(db_path) as conn:
                row = conn.execute(
                    "SELECT document_id FROM documents WHERE tenant_id = ? AND name = ?",
                    (tenant_id, filename),
                ).fetchone()
                doc_id = row["document_id"] if row else _document_id(file_path)
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                cur = conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                deleted = cur.rowcount > 0
                conn.commit()
        except Exception:
            pass
    # Idempotent delete: avoid surfacing noisy 404s in UI if an item is already gone.
    if not deleted and not file_deleted and not file_existed:
        return {"status": "not_found", "filename": filename}
    return {"status": "deleted", "filename": filename}


# --- CLOUD SYNC, SCRAPE, OCR APIs ---

def _run_isolation_check():
    tenants = admin_store.list_tenants()
    results = []
    total_isolated = 0
    all_clean = True
    for t in tenants:
        tid = t["tenant_id"]
        db_path = _tenant_db_path(tid, t)
        db_exists = db_path.exists()
        db_clean = True
        doc_count = 0
        chunk_count = 0
        if db_exists:
            try:
                with _tenant_connection(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    foreign = conn.execute("SELECT COUNT(*) FROM chunks WHERE tenant_id != ?", (tid,)).fetchone()[0]
                    if foreign > 0:
                        db_clean = False
                        all_clean = False
                    doc_count = conn.execute("SELECT COUNT(*) FROM documents WHERE tenant_id = ?", (tid,)).fetchone()[0]
                    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE tenant_id = ?", (tid,)).fetchone()[0]
            except Exception:
                db_clean = False
        is_isolated = db_exists and db_clean
        if is_isolated:
            total_isolated += 1
        results.append({"tenant_id": tid, "name": t["name"], "status": t["status"], "isolated": is_isolated, "doc_count": doc_count, "chunk_count": chunk_count})
    score = 100.0 if (len(tenants) == 0 or total_isolated == len(tenants)) else (total_isolated / len(tenants)) * 100.0
    return {"status": "verified" if all_clean else "warning", "score_percent": score, "total_tenants": len(tenants), "verified_isolated": total_isolated, "details": results}


@app.get("/api/v1/isolation-check")
def run_isolation_check(_admin=Depends(require_admin)):
    return _run_isolation_check()


@app.post("/api/v1/client/cloud-sync")
def client_trigger_cloud_sync(req: CloudSyncRequest, background_tasks: BackgroundTasks, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    try:
        res = sync_cloud_documents(tenant_id=tenant_id, tenants_dir=TENANTS_DIR, provider=req.provider, cloud_url_or_id=req.cloud_url_or_id, api_key_or_token=req.api_key_or_token, custom_filename=req.custom_filename)
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if res.get("downloaded") else "WARNING", operation="CLOUD_SYNC", message=f"Cloud sync ({req.provider}): {len(res.get('downloaded', []))} file(s)", details={"provider": req.provider, "downloaded": res.get("downloaded", []), "errors": res.get("errors", [])})
        if req.auto_ingest and res.get("count", 0) > 0:
            if tenant_id not in ingestion_status or ingestion_status[tenant_id]["status"] != "running":
                ingestion_status[tenant_id] = {"status": "running", "logs": [f"[Cloud Sync] Auto-ingesting {res['count']} document(s)..."], "progress": 0, "summary": None}
                _sync_ingestion_to_redis(tenant_id)
                background_tasks.add_task(_run_ingestion_background, tenant_id, tenant)
        return res
    except Exception as exc:
        tb_str = traceback.format_exc()
        admin_store.log_activity(tenant_id=tenant_id, level="ERROR", operation="CLOUD_SYNC", message=f"Cloud sync failed: {exc}", traceback=tb_str)
        raise HTTPException(status_code=500, detail=f"Cloud sync error: {exc}")


@app.post("/api/v1/tenants/{tenant_id}/cloud-sync")
def trigger_cloud_sync(tenant_id: str, req: CloudSyncRequest, background_tasks: BackgroundTasks, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        res = sync_cloud_documents(tenant_id=tenant_id, tenants_dir=TENANTS_DIR, provider=req.provider, cloud_url_or_id=req.cloud_url_or_id, api_key_or_token=req.api_key_or_token, custom_filename=req.custom_filename)
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if res.get("downloaded") else "WARNING", operation="CLOUD_SYNC", message=f"Cloud sync ({req.provider}): {len(res.get('downloaded', []))} file(s)", details={"provider": req.provider, "downloaded": res.get("downloaded", []), "errors": res.get("errors", [])})
        if req.auto_ingest and res.get("count", 0) > 0:
            if tenant_id not in ingestion_status or ingestion_status[tenant_id]["status"] != "running":
                ingestion_status[tenant_id] = {"status": "running", "logs": [f"[Cloud Sync] Auto-ingesting {res['count']} document(s)..."], "progress": 0, "summary": None}
                _sync_ingestion_to_redis(tenant_id)
                background_tasks.add_task(_run_ingestion_background, tenant_id, tenant)
        return res
    except Exception as exc:
        tb_str = traceback.format_exc()
        admin_store.log_activity(tenant_id=tenant_id, level="ERROR", operation="CLOUD_SYNC", message=f"Cloud sync failed: {exc}", traceback=tb_str)
        raise HTTPException(status_code=500, detail=f"Cloud sync error: {exc}")


@app.post("/api/v1/tenants/{tenant_id}/scrape")
async def scrape_url(tenant_id: str, req: ScrapeRequest, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    try:
        if req.crawl:
            job = await scraper.crawl_url(req.url, max_pages=req.max_pages, max_depth=req.max_depth, full_site=req.full_site)
        else:
            job = await scraper.scrape_url(req.url)
        pages = [
            {"text": r.get("text", ""), "metadata": r.get("metadata", {})}
            for r in (job.results or []) if r.get("text")
        ]
        saved_files, duplicates = _save_scraped_pages(tenant_id, pages, req.url)
        if saved_files:
            _save_crawl_output(
                site=_crawl_site_slug(req.url),
                metadata={"strategy": "crawl" if req.crawl else "single", "is_wordpress": False, "languages_found": [], "source_url": req.url},
                pages=[f"# {f['title']}\n\nSource: {f['url']}\n\n" for f in saved_files],
            )
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if saved_files else "WARNING", operation="SCRAPE",
                                message=f"Scraped {req.url}: {len(saved_files)} file(s), {len(duplicates)} duplicate(s)",
                                details={"url": req.url, "files": saved_files, "duplicates": duplicates})
        return {"status": "completed" if saved_files else "failed", "job_id": job.job_id, "url": req.url,
                "files_saved": len(saved_files), "files": saved_files, "duplicates": duplicates, "error": job.error}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {e}")


@app.get("/api/v1/tenants/{tenant_id}/scrape/jobs")
async def list_scrape_jobs(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    scraper = _get_scraper_service()
    return {"jobs": [j.to_dict() for j in scraper.list_jobs()]}


@app.get("/api/v1/tenants/{tenant_id}/scrape/jobs/{job_id}")
async def get_scrape_job(tenant_id: str, job_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    scraper = _get_scraper_service()

    # Full-site jobs run asynchronously in the microservice's own job store.
    if scraper.is_full_job(job_id):
        m = scraper.get_full_crawl_status(job_id)
        data = m.get("data", {}) if isinstance(m, dict) else {}
        status = data.get("status", "running")
        if status in ("done", "completed"):
            if not scraper.was_full_imported(job_id):
                _import_full_crawl_output(tenant_id, job_id, scraper)
                scraper.mark_full_imported(job_id)
                admin_store.log_activity(tenant_id=tenant_id, level="INFO", operation="SCRAPE_FULL",
                                         message=f"Full crawl {job_id} completed and imported.",
                                         details={"job_id": job_id})
            return {"success": True, "status": "done", "data": data}
        return {"success": True, "status": status, "data": data}

    job = await scraper.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


class FullScrapeRequest(BaseModel):
    url: str
    max_pages: int = 50
    max_depth: int = 3
    download_images: bool = False
    download_pdfs: bool = True
    workers: int = 4
    respect_robots: bool = True


_PENDING_DIR = ".pending"


def _friendly_unique_name(docs_dir: Path, base_name: str, used: set[str] | None = None) -> str:
    """Return base_name without clobbering an existing file, appending ' (n)'
    before the extension (never random hex garbage)."""
    used = used or set()
    stem = Path(base_name).stem
    ext = Path(base_name).suffix or ".txt"
    candidate = base_name
    n = 2
    while candidate in used or (docs_dir / candidate).exists():
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


def _save_scraped_pages(tenant_id: str, pages: list[dict], base_url: str, ext: str = ".txt") -> tuple[list[dict], list[dict]]:
    """Write scraped page content into the tenant docs dir with duplicate control.

    - URLs not scraped yet  → written to docs_dir, returned in saved_files.
    - URLs already scraped (same ``Source:`` header) → written to ``.pending/``
      (invisible to the docs list, queue, and ingestion) and returned as
      duplicates for the user to Remove / Keep both / Rename via the
      resolve-duplicates endpoint.

    Returns (saved_files, duplicates); each duplicate =
    {url, title, existing_file, new_file} where new_file lives in .pending/.
    """
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    pending_dir = docs_dir / _PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)

    existing_url_map = _scan_existing_urls(tenant_id)
    saved_files: list[dict] = []
    duplicates: list[dict] = []
    used = set(existing_url_map.values())

    for page in pages:
        text = page.get("text") or page.get("markdown") or page.get("content", "")
        if not text:
            continue
        meta = page.get("metadata", {})
        source_url = meta.get("url") or meta.get("source_url") or base_url
        title = meta.get("title") or meta.get("og_title") or "Untitled"
        base_name = _make_relevant_filename(title=title, url=source_url, prefix="scraped")
        if not base_name.endswith(ext):
            base_name = Path(base_name).stem + ext
        content = f"# {title}\n\nSource: {source_url}\n\n{text}"

        if source_url in existing_url_map:
            # Duplicate → stage for the user to decide; never auto-add to the queue.
            pending_name = _friendly_unique_name(pending_dir, base_name, used)
            (pending_dir / pending_name).write_text(content, encoding="utf-8")
            used.add(pending_name)
            duplicates.append({
                "url": source_url,
                "title": title,
                "existing_file": existing_url_map[source_url],
                "new_file": pending_name,
            })
        else:
            name = _friendly_unique_name(docs_dir, base_name, used)
            (docs_dir / name).write_text(content, encoding="utf-8")
            used.add(name)
            existing_url_map[source_url] = name
            saved_files.append({"url": source_url, "file": name, "title": title})

    return saved_files, duplicates


def _save_pages_from_full_crawl(tenant_id: str, result: dict, base_url: str) -> tuple[list[dict], list[dict]]:
    """Parse crawl_full() output and delegate duplicate-aware saving.
    Returns (saved_files, duplicates) where duplicates = [{url, existing_file, new_file, title}]."""
    data = result.get("data", result)
    # crawl_full returns {"data": {"pages": [...]}} or {"pages": [...]}
    pages = data.get("pages") or data.get("results") or []
    if not pages and result.get("markdown"):
        pages = [{"text": result.get("markdown", ""), "metadata": {"url": base_url, "title": "Page"}}]
    return _save_scraped_pages(tenant_id, pages, base_url)


def _import_full_crawl_output(tenant_id: str, job_id: str, scraper) -> list[dict]:
    """Once a microservice full-crawl job reports done, fetch its output manifest
    over HTTP (works even when rag_api has no volume access) and import every
    page into the tenant's documents dir. Duplicate URLs are handled by
    _save_scraped_pages (re-scans land in .pending for user resolution)."""
    out = scraper.get_full_crawl_output(job_id)
    if not out or not out.get("success"):
        return []
    data = out.get("data", {}) if isinstance(out.get("data"), dict) else {}
    site = data.get("site") or data.get("source_url") or ""
    pages: list[dict] = []
    for p in data.get("pages") or []:
        if not isinstance(p, dict):
            continue
        rel = p.get("clean_text_path") or p.get("file")
        if not rel:
            continue
        text = scraper.download_crawl_file(job_id, rel)
        if not text:
            continue
        pages.append({"text": text, "metadata": {"url": p.get("url") or site, "title": p.get("title") or "Untitled"}})
    if not pages:
        return []
    saved, duplicates = _save_scraped_pages(tenant_id, pages, site)
    if saved:
        _save_crawl_output(
            site=_crawl_site_slug(site or "crawl"),
            metadata={"strategy": "full", "is_wordpress": False, "languages_found": [], "source_url": site},
            pages=[f"# {f['title']}\n\nSource: {f['url']}" for f in saved],
        )
    return saved




@app.post("/api/v1/scrape/full")
async def full_scrape(req: FullScrapeRequest, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    try:
        result = scraper.crawl_full(
            req.url,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
            download_images=req.download_images,
            download_pdfs=req.download_pdfs,
            workers=req.workers,
            respect_robots=req.respect_robots,
        )
        job_id = (result.get("data") or {}).get("job_id") or result.get("job_id")
        if job_id:
            scraper.track_full_job(job_id)
        if job_id and scraper.is_full_job(job_id):
            # Async crawl just started in the microservice — return the job so the
            # client can poll for progress. Output is imported on completion.
            return {
                "success": True,
                "status": "running",
                "job_id": job_id,
                "data": {"job_id": job_id, "status": "running", "url": req.url, "files_saved": 0, "files": [], "duplicates": []},
                "files_saved": 0, "files": [], "duplicates": [],
            }
        saved_files, duplicates = _save_pages_from_full_crawl(tenant_id, result, req.url)
        if saved_files:
            _save_crawl_output(
                site=_crawl_site_slug(req.url),
                metadata={"strategy": "full", "is_wordpress": False, "languages_found": [], "source_url": req.url},
                pages=[f"# {f['title']}\n\nSource: {f['url']}" for f in saved_files],
            )
        if tenant_id:
            _sync_site_to_tenant(tenant_id, req.url)
        admin_store.log_activity(
            tenant_id=tenant_id,
            level="INFO" if saved_files else "WARNING",
            operation="SCRAPE_FULL",
            message=f"Full site scrape {req.url}: {len(saved_files)} page(s), {len(duplicates)} duplicate(s)",
            details={"url": req.url, "files": saved_files, "duplicates": duplicates},
        )
        return {
            "success": True,
            "status": "completed" if saved_files else "failed",
            "data": {"job_id": job_id, "url": req.url, "files_saved": len(saved_files), "files": saved_files},
            "files_saved": len(saved_files),
            "files": saved_files,
            "duplicates": duplicates,
        }
    except Exception as e:
        log.exception("Full scrape error: %s", e)
        return {"success": False, "status": "failed", "error": str(e), "data": {"job_id": None}}


@app.post("/api/v1/tenants/{tenant_id}/scrape/full")
async def tenant_full_scrape(tenant_id: str, req: FullScrapeRequest, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    try:
        result = scraper.crawl_full(
            req.url,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
            download_images=req.download_images,
            download_pdfs=req.download_pdfs,
            workers=req.workers,
            respect_robots=req.respect_robots,
        )
        job_id = (result.get("data") or {}).get("job_id") or result.get("job_id")
        if job_id:
            scraper.track_full_job(job_id)
            # Async microservice crawl just started — admin polls
            # /scrape/jobs/{job_id}, which proxies status and imports on done.
            return {
                "success": True,
                "status": "processing",
                "job_id": job_id,
                "data": {"job_id": job_id, "status": "running", "url": req.url, "files_saved": 0, "files": [], "duplicates": []},
                "files_saved": 0, "files": [], "duplicates": [],
            }
        saved_files, duplicates = _save_pages_from_full_crawl(tenant_id, result, req.url)
        if saved_files:
            _save_crawl_output(
                site=_crawl_site_slug(req.url),
                metadata={"strategy": "full", "is_wordpress": False, "languages_found": [], "source_url": req.url},
                pages=[f"# {f['title']}\n\nSource: {f['url']}" for f in saved_files],
            )
        _sync_site_to_tenant(tenant_id, req.url)
        admin_store.log_activity(
            tenant_id=tenant_id,
            level="INFO" if saved_files else "WARNING",
            operation="SCRAPE_FULL",
            message=f"Full site scrape {req.url}: {len(saved_files)} page(s), {len(duplicates)} duplicate(s)",
            details={"url": req.url, "files": saved_files, "duplicates": duplicates},
        )
        return {
            "success": True,
            "status": "completed" if saved_files else "running",
            "job_id": job_id,
            "data": {"job_id": job_id, "url": req.url, "files_saved": len(saved_files), "files": saved_files},
            "files_saved": len(saved_files),
            "files": saved_files,
            "duplicates": duplicates,
        }
    except Exception as e:
        log.exception("Full scrape error: %s", e)
        return {"success": False, "status": "failed", "error": str(e), "data": {"job_id": None}}


@app.get("/api/v1/scrape/full/status/{job_id}")
async def get_full_scrape_status(job_id: str):
    scraper = _get_scraper_service()
    job = await scraper.get_job(job_id)
    status_str = job.status if job else "done"
    return {"success": True, "data": {"status": status_str, "job_id": job_id}}


# ── Enhanced Scraper Endpoints (smart crawl, wordpress, facebook, deepcrawl) ──

class EnhancedScrapeRequest(BaseModel):
    url: str
    scrape_type: str = "single"  # single, smart, recursive, wordpress, facebook, profile
    max_pages: int = 50
    max_depth: int = 3
    timeout: int = 30
    format: str = "markdown"
    # WordPress
    include_pages: bool = True
    include_media: bool = True
    # Facebook
    fb_c_user: str = ""
    fb_xs: str = ""
    fb_max_posts: int = 20
    fb_scroll_rounds: int = 5
    fb_date_from: str = ""
    fb_date_to: str = ""
    # Profile
    profile_platform: str = ""
    profile_username: str = ""
    # Recursive crawl
    workers: int = 1
    respect_robots: bool = True
    allowed_domains: list[str] | None = None


@app.post("/api/v1/scrape/enhanced")
async def enhanced_scrape(req: EnhancedScrapeRequest, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    result = None

    if req.scrape_type == "smart":
        result = scraper.crawl_smart(req.url, timeout=req.timeout)
    elif req.scrape_type == "recursive":
        result = scraper.crawl_recursive(req.url, max_depth=req.max_depth, max_pages=req.max_pages,
                                           workers=req.workers, respect_robots=req.respect_robots,
                                           allowed_domains=req.allowed_domains)
    elif req.scrape_type == "wordpress":
        result = scraper.scrape_wordpress(req.url, max_pages=req.max_pages,
                                           include_pages=req.include_pages, include_media=req.include_media)
    elif req.scrape_type == "facebook":
        result = scraper.scrape_facebook(req.url, c_user=req.fb_c_user, xs=req.fb_xs,
                                          max_posts=req.fb_max_posts, scroll_rounds=req.fb_scroll_rounds,
                                          date_from=req.fb_date_from, date_to=req.fb_date_to)
    elif req.scrape_type == "profile":
        result = scraper.scrape_profile(req.profile_platform, req.profile_username)
    else:
        result = scraper.crawl_single(req.url, format=req.format)

    if result and result.get("success") and req.scrape_type in ("smart", "single"):
        data = result.get("data", {})
        content_text = data.get("markdown") or data.get("text") or ""
        title = data.get("title") or data.get("og_title") or req.url.rstrip("/").split("/")[-1] or "page"
        ext = ".md" if req.format == "markdown" else ".txt"
        if content_text:
            pages = [{"text": content_text, "metadata": {"url": req.url, "title": title}}]
            saved_files, duplicates = _save_scraped_pages(tenant_id, pages, req.url, ext=ext)
            result_out = dict(result or {})
            result_out["saved_files"] = saved_files
            result_out["files_saved"] = len(saved_files)
            result_out["duplicates"] = duplicates
            return result_out

    result_out = result or {}
    result_out["saved_files"] = []
    result_out["files_saved"] = 0
    result_out["duplicates"] = []
    return result_out


@app.post("/api/v1/tenants/{tenant_id}/scrape/enhanced")
async def tenant_enhanced_scrape(tenant_id: str, req: EnhancedScrapeRequest, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _validate_scrape_url(req.url)
    scraper = _get_scraper_service()
    result = None

    if req.scrape_type == "smart":
        result = scraper.crawl_smart(req.url, timeout=req.timeout)
    elif req.scrape_type == "recursive":
        result = scraper.crawl_recursive(req.url, max_depth=req.max_depth, max_pages=req.max_pages,
                                           workers=req.workers, respect_robots=req.respect_robots,
                                           allowed_domains=req.allowed_domains)
    elif req.scrape_type == "wordpress":
        result = scraper.scrape_wordpress(req.url, max_pages=req.max_pages,
                                           include_pages=req.include_pages, include_media=req.include_media)
    elif req.scrape_type == "facebook":
        result = scraper.scrape_facebook(req.url, c_user=req.fb_c_user, xs=req.fb_xs,
                                          max_posts=req.fb_max_posts, scroll_rounds=req.fb_scroll_rounds,
                                          date_from=req.fb_date_from, date_to=req.fb_date_to)
    elif req.scrape_type == "profile":
        result = scraper.scrape_profile(req.profile_platform, req.profile_username)
    else:
        result = scraper.crawl_single(req.url, format=req.format)

    saved_files = []
    duplicates = []
    if result and result.get("success") and req.scrape_type in ("smart", "single"):
        data = result.get("data", {})
        # Prefer markdown content, fall back to text
        content_text = data.get("markdown") or data.get("text") or ""
        title = data.get("title") or data.get("og_title") or req.url.rstrip("/").split("/")[-1] or "page"
        ext = ".md" if req.format == "markdown" else ".txt"
        if content_text:
            pages = [{"text": content_text, "metadata": {"url": req.url, "title": title}}]
            saved_files, duplicates = _save_scraped_pages(tenant_id, pages, req.url, ext=ext)

        _save_crawl_output(
            site=_crawl_site_slug(req.url),
            metadata={"strategy": req.scrape_type, "is_wordpress": False, "languages_found": [], "source_url": req.url, "quality_score": data.get("quality_score")},
            pages=[content_text],
        )

    result_out = result or {}
    result_out["saved_files"] = saved_files
    result_out["files_saved"] = len(saved_files)
    result_out["duplicates"] = duplicates
    return result_out


@app.get("/api/v1/scrape/recursive/{job_id}/status")
async def get_recursive_job_status(job_id: str, tenant=Depends(_resolve_client_tenant)):
    scraper = _get_scraper_service()
    return scraper.get_recursive_status(job_id)


@app.get("/api/v1/scrape/recursive/jobs")
async def list_recursive_jobs(tenant=Depends(_resolve_client_tenant)):
    scraper = _get_scraper_service()
    return {"jobs": scraper.list_recursive_jobs()}


@app.get("/api/v1/scrape/platforms")
async def get_scrape_platforms():
    scraper = _get_scraper_service()
    return {"platforms": scraper.get_platforms()}


@app.get("/api/v1/scrape/health")
async def scraper_health():
    scraper = _get_scraper_service()
    return scraper.health()


@app.get("/api/v1/scrape/logs")
async def scraper_logs(lines: int = Query(default=50, le=500), _admin=Depends(require_admin)):
    scraper = _get_scraper_service()
    data = scraper.get_logs(lines)
    return {"logs": data.get("logs", [])}


@app.get("/api/v1/tenants/{tenant_id}/scrape/recursive/{job_id}/status")
async def admin_recursive_job_status(tenant_id: str, job_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    scraper = _get_scraper_service()
    return scraper.get_recursive_status(job_id)


def _crawl_site_slug(url: str) -> str:
    try:
        return urlparse(url).netloc or url.replace("https://", "").replace("http://", "").split("/")[0]
    except Exception:
        return url.replace("https://", "").replace("http://", "").split("/")[0]


def _find_crawl_site_dir(url: str) -> Path | None:
    """Locate the crawler output site folder matching a scraped URL, if it exists."""
    candidates = [
        ROOT_DIR / "crawl-output",
        Path("scraper-service/crawl_output"),
        Path("scraper-service/app/crawl_output"),
    ]
    host = _crawl_site_slug(url)
    host_unders = host.replace(".", "_")
    for base_dir in candidates:
        if not base_dir.exists():
            continue
        for site_dir in base_dir.iterdir():
            if not site_dir.is_dir():
                continue
            if site_dir.name == host or site_dir.name == host_unders:
                return site_dir
            # Also match via index.json's site/origin field
            index_file = site_dir / "index.json"
            if index_file.exists():
                try:
                    data = json.loads(index_file.read_text(encoding="utf-8", errors="ignore"))
                    site_field = str(data.get("site") or data.get("source_url") or data.get("origin") or "")
                    if host in site_field:
                        return site_dir
                except Exception:
                    pass
    return None


def _sync_site_to_tenant(tenant_id: str, url: str) -> list[dict]:
    """After a crawl completes, record the crawl output folder on the tenant and
    import all its documents (md/json/pdf, original extensions) into the tenant."""
    site_dir = _find_crawl_site_dir(url)
    if site_dir and site_dir.exists():
        admin_store.set_crawl_output_dir(tenant_id, str(site_dir))
    return _sync_crawl_outputs_to_tenant(tenant_id, site_url=url, site_dir=site_dir)


def _save_crawl_output(site: str, metadata: dict, pages: list[str], images: list[str] | None = None, pdfs: list[str] | None = None) -> None:
    """Persist a crawl result to the local crawl-output catalog (site folders)."""
    try:
        site_dir = CRAWL_OUTPUT_DIR / site
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "metadata.json").write_text(
            json.dumps({"site": site, **metadata, "crawled_at": metadata.get("crawled_at") or datetime.utcnow().isoformat()}),
            encoding="utf-8",
        )
        for idx, page in enumerate(pages):
            page_dir = site_dir / "pages"
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / f"{idx + 1:04d}.md").write_text(page, encoding="utf-8")
        for kind in ("images", "pdfs"):
            items = {"images": images, "pdfs": pdfs}.get(kind) or []
            if items:
                kind_dir = site_dir / kind
                kind_dir.mkdir(parents=True, exist_ok=True)
                for item in items:
                    name = Path(str(item).split("?")[0]).name or f"{uuid.uuid4().hex}"
                    if name and not (kind_dir / name).exists():
                        (kind_dir / name).write_text(str(item), encoding="utf-8")
    except Exception:
        log.exception("Failed to persist crawl output for %s", site)


@app.get("/api/v1/crawl-output")
def list_crawl_output(_admin=Depends(require_admin)):
    sites = []
    if CRAWL_OUTPUT_DIR.exists():
        for site_dir in sorted(CRAWL_OUTPUT_DIR.iterdir()):
            if not site_dir.is_dir():
                continue
            meta = {}
            meta_path = site_dir / "metadata.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            pages = list((site_dir / "pages").glob("*")) if (site_dir / "pages").exists() else []
            images = list((site_dir / "images").glob("*")) if (site_dir / "images").exists() else []
            pdfs = list((site_dir / "pdfs").glob("*")) if (site_dir / "pdfs").exists() else []
            sites.append({
                "site": site_dir.name,
                "metadata": meta,
                "hasPages": bool(pages),
                "hasImages": bool(images),
                "hasPdfs": bool(pdfs),
            })
    return {"sites": sites}


@app.get("/api/v1/crawl-output/{site}")
def get_crawl_output_site(site: str, _admin=Depends(require_admin)):
    site_dir = CRAWL_OUTPUT_DIR / Path(site).name
    if not site_dir.exists() or not site_dir.is_dir():
        raise HTTPException(status_code=404, detail="Crawl output not found")
    meta = {}
    meta_path = site_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    files = {"pages": [], "images": [], "pdfs": []}
    for kind in files:
        kind_dir = site_dir / kind
        if kind_dir.exists():
            files[kind] = sorted(p.name for p in kind_dir.iterdir() if p.is_file())
    return {"site": site_dir.name, "metadata": meta, "files": files}


@app.post("/api/v1/crawl-output/{site}/import")
def import_crawl_output(site: str, req: dict = Body(default={}), _admin=Depends(require_admin)):
    tenant_id = (req or {}).get("tenantId")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenantId is required")
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    site_dir = CRAWL_OUTPUT_DIR / Path(site).name
    if not site_dir.exists() or not site_dir.is_dir():
        raise HTTPException(status_code=404, detail="Crawl output not found")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    page_dir = site_dir / "pages"
    if page_dir.exists():
        for p in sorted(page_dir.iterdir()):
            if not p.is_file():
                continue
            dest = docs_dir / f"crawl_output_{site}_{p.name}"
            if not dest.exists():
                shutil.copyfile(p, dest)
                imported += 1
    if imported and tenant_id not in ingestion_status or (tenant_id in ingestion_status and ingestion_status[tenant_id]["status"] != "running"):
        ingestion_status[tenant_id] = {"status": "running", "logs": [f"[Crawl Import] Importing {imported} page(s) from {site}..."], "progress": 0, "summary": None}
        _sync_ingestion_to_redis(tenant_id)
        import threading
        threading.Thread(target=_run_ingestion_background, args=(tenant_id, tenant), daemon=True).start()
    return {"success": True, "imported_count": imported, "site": site, "tenant_id": tenant_id}


@app.post("/api/v1/tenants/{tenant_id}/scrape/enhanced/ingest")
async def enhanced_scrape_and_ingest(tenant_id: str, req: EnhancedScrapeRequest, _admin=Depends(require_admin)):
    from rbs_rag.services.scraper_service import scrape_and_ingest as _scrape_and_ingest
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _validate_scrape_url(req.url)
    config = _get_tenant_config(tenant)
    store = SQLiteRagStore(Path(config.storage.path))
    result = _scrape_and_ingest(config, store, req.url, tenant_id, scrape_type=req.scrape_type, timeout=req.timeout)
    if result["status"] == "completed":
        admin_store.log_activity(tenant_id, "INFO", "scrape_ingest",
                                  f"Scraped and ingested {req.url} -> {result.get('document', '')}")
    return result


@app.post("/api/v1/scrape/enhanced/ingest")
async def client_enhanced_scrape_and_ingest(req: EnhancedScrapeRequest, tenant=Depends(_resolve_client_tenant)):
    from rbs_rag.services.scraper_service import scrape_and_ingest as _scrape_and_ingest
    _validate_scrape_url(req.url)
    config = _get_tenant_config(tenant)
    store = SQLiteRagStore(Path(config.storage.path))
    result = _scrape_and_ingest(config, store, req.url, tenant["tenant_id"], scrape_type=req.scrape_type, timeout=req.timeout)
    return result


@app.post("/api/v1/tenants/{tenant_id}/ocr")
async def ocr_document(tenant_id: str, file: UploadFile = File(...), _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename).name
    try:
        target_path = _resolve_tenant_document_path(tenant_id, filename, docs_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    ocr_svc = get_ocr_service()
    ocr_result = ocr_svc.process(target_path)
    if ocr_result and ocr_result.full_text.strip():
        ocr_text_path = docs_dir / f"{target_path.stem}_ocr.txt"
        ocr_text_path.write_text(ocr_result.full_text, encoding="utf-8")
        return {"status": "success", "filename": filename, "ocr_text_file": ocr_text_path.name, "total_words": ocr_result.total_words, "processing_time_ms": ocr_result.processing_time_ms, "engine": ocr_result.engine}
    return {"status": "completed", "filename": filename, "ocr_text_file": None, "message": "No text extracted"}


@app.get("/api/v1/system/ocr-status")
async def get_ocr_status(_admin=Depends(require_admin)):
    try:
        ocr_svc = get_ocr_service()
        engines = ocr_svc.get_available_engines()
        return {"status": "available" if engines else "unavailable", "engines": engines or []}
    except Exception as e:
        return {"status": "unavailable", "error": str(e), "engines": []}


# --- CHAT SESSION MANAGEMENT ---

@app.get("/api/v1/tenants/{tenant_id}/sessions")
def list_tenant_sessions(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    engine = _get_engine(tenant)
    retention_days = tenant.get("chat_retention_days", 30)
    if retention_days > 0:
        engine.store.purge_expired_sessions(tenant_id, retention_days)
    return {"sessions": engine.store.list_sessions(tenant_id), "retention_days": retention_days}


@app.get("/api/v1/tenants/{tenant_id}/sessions/{session_id}/turns")
def get_session_turns(tenant_id: str, session_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    engine = _get_engine(tenant)
    return {"tenant_id": tenant_id, "session_id": session_id, "turns": engine.store.get_session_turns(tenant_id, session_id)}


@app.delete("/api/v1/tenants/{tenant_id}/sessions/{session_id}")
def delete_chat_session(tenant_id: str, session_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    engine = _get_engine(tenant)
    engine.store.delete_session(tenant_id, session_id)
    return {"status": "success", "deleted_session_id": session_id}


@app.post("/api/v1/tenants/{tenant_id}/sessions/purge")
def purge_chat_sessions(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    engine = _get_engine(tenant)
    retention_days = tenant.get("chat_retention_days", 30)
    purged_count = engine.store.purge_expired_sessions(tenant_id, retention_days)
    return {"status": "success", "purged_turns": purged_count, "retention_days": retention_days}


# --- SYSTEM LOGS ---

@app.get("/api/v1/system/logs")
def list_system_logs(tenant_id: str | None = None, level: str | None = None, limit: int = 100, _admin=Depends(require_admin)):
    return {"logs": admin_store.get_activity_logs(tenant_id=tenant_id, level=level, limit=limit)}


# --- TERMINAL ---

@app.post("/api/v1/terminal/exec")
def execute_terminal_command(req: TerminalExecRequest, _admin=Depends(require_admin)):
    terminal_enabled = os.getenv("RAG_TERMINAL_ENABLED", "true").lower() == "true"
    if not terminal_enabled:
        return {"output": "Terminal is disabled.", "type": "error"}
    raw_cmd = req.command.strip()
    if not raw_cmd:
        return {"output": "", "type": "empty"}
    cmd_parts = raw_cmd.split()
    cmd = cmd_parts[0].lower().lstrip("/")
    args = cmd_parts[1:]

    COMMAND_HELP = {
        "help": {"summary": "Display command catalog", "usage": "help [command]", "description": "Lists all interactive console commands."},
        "isolation": {"summary": "Run multi-tenant isolation audit", "usage": "isolation", "description": "Performs cross-database security audit."},
        "clients": {"summary": "List all tenants", "usage": "clients", "description": "Displays all onboarded clients."},
        "sync": {"summary": "Sync cloud documents", "usage": "sync <provider> <url> [token]", "description": "Downloads cloud documents."},
        "ingest": {"summary": "Trigger ingestion", "usage": "ingest [tenant_id]", "description": "Starts background ingestion pipeline."},
        "query": {"summary": "Run RAG query", "usage": "query <question>", "description": "Executes hybrid retrieval and LLM generation."},
        "chunks": {"summary": "Inspect document chunks", "usage": "chunks [filename]", "description": "Fetches chunks for a file."},
        "theme": {"summary": "Switch UI theme", "usage": "theme <name>", "description": "Dynamically switches theme."},
        "status": {"summary": "System health", "usage": "status", "description": "Returns runtime metrics."},
        "clear": {"summary": "Clear screen", "usage": "clear", "description": "Wipes terminal output."},
    }

    if cmd in {"help", "?"}:
        if args:
            sub = args[0].lower().lstrip("/")
            if sub in COMMAND_HELP:
                info = COMMAND_HELP[sub]
                return {"output": f"COMMAND: /{sub.upper()}\nSummary: {info['summary']}\nUsage: {info['usage']}\n\n{info['description']}", "type": "help_detail"}
            return {"output": f"Unknown '{sub}'", "type": "error"}
        lines = ["COMMAND CATALOG:"] + [f"  /{c:<12} - {m['summary']}" for c, m in COMMAND_HELP.items()]
        return {"output": "\n".join(lines), "type": "help_catalog"}

    if cmd in {"isolation", "audit"}:
        check = _run_isolation_check()
        lines = [f"ISOLATION AUDIT: Status={check['status']}, Score={check['score_percent']:.1f}%, Tenants={check['total_tenants']}, Isolated={check['verified_isolated']}"]
        for item in check["details"]:
            lines.append(f"  {item['tenant_id']}: isolated={item['isolated']}, docs={item['doc_count']}, chunks={item['chunk_count']}")
        return {"output": "\n".join(lines), "type": "isolation_report", "raw": check}

    if cmd in {"clients", "tenants"}:
        tenants = admin_store.list_tenants()
        if not tenants:
            return {"output": "No tenants found.", "type": "info"}
        lines = ["TENANTS:"] + [f"  [{t['tenant_id']}] {t['name']} ({t.get('subscription_tier', 'basic').upper()}) - {t.get('llm_provider', '?')}/{t.get('llm_model', '?')}" for t in tenants]
        return {"output": "\n".join(lines), "type": "clients_list"}

    if cmd in {"status"}:
        return {"output": f"SYSTEM STATUS: Operational. Root: {ROOT_DIR.resolve()}. Admin DB: {ADMIN_DB_PATH}. Tenants: {len(admin_store.list_tenants())}.", "type": "status"}

    if cmd in {"clear"}:
        return {"output": "", "type": "clear"}

    if cmd in {"theme"}:
        if args:
            return {"output": f"Theme set to '{args[0]}'", "type": "theme", "theme": args[0]}
        return {"output": "Usage: /theme <name>", "type": "info"}

    if cmd in {"ingest"}:
        tid = req.tenant_id
        if not tid:
            return {"output": "Error: No tenant selected.", "type": "error"}
        tenant = admin_store.get_tenant(tid)
        if not tenant:
            return {"output": f"Error: Tenant '{tid}' not found.", "type": "error"}
        trigger_ingestion(tid, BackgroundTasks())
        return {"output": f"Ingestion started for '{tid}'.", "type": "success"}

    if cmd in {"query", "ask"}:
        tid = req.tenant_id
        if not tid:
            return {"output": "Error: No tenant selected.", "type": "error"}
        qtext = " ".join(args)
        if not qtext:
            return {"output": "Usage: /query <question>", "type": "info"}
        tenant = admin_store.get_tenant(tid)
        if not tenant:
            return {"output": f"Error: Tenant '{tid}' not found.", "type": "error"}
        engine = _get_engine(tenant)
        ans = engine.ask(query=qtext, session_id="terminal-tester")
        return {"output": f"Q: {qtext}\nA: {ans.text}\nConfidence: {ans.validation.confidence.upper()}", "type": "query_res"}

    return {"output": f"Unknown command '{cmd}'. Type '/help' for commands.", "type": "error"}


# ── SPA fallback: serve index.html for unmatched browser routes ──────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class SPAFallbackMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404 and request.method == "GET":
            accept = request.headers.get("accept", "")
            if "text/html" in accept and not request.url.path.startswith("/api/"):
                html = _get_spa_index()
                if html:
                    resp = HTMLResponse(content=html)
                    resp.headers["Cache-Control"] = "no-store"
                    return resp
        return response

app.add_middleware(SPAFallbackMiddleware)