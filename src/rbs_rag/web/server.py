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

from fastapi import FastAPI, UploadFile, File, Header, HTTPException, BackgroundTasks, Depends, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rbs_rag.config import AppConfig, StorageConfig, EmbeddingConfig, RetrievalConfig, ChunkingConfig, QdrantConfig, RateLimitConfig, SecurityConfig, ObservabilityConfig
from rbs_rag.llm import LLMSettings
from rbs_rag.engine import RagEngine
from rbs_rag.document_loaders import _document_id, load_document
from rbs_rag.cloud_sync import sync_cloud_documents
from rbs_rag.security import detect_prompt_injection, generate_jwt, verify_jwt
from rbs_rag.metrics import MetricsMiddleware, metrics_export, DOCUMENTS_INGESTED, CHUNKS_CREATED, CHUNKS_RETRIEVED, LLM_REQUESTS, LLM_DURATION, PROMPT_INJECTIONS_BLOCKED, ACTIVE_TENANTS, ENGINE_UPTIME
from rbs_rag.web.admin_db import AdminStore
from rbs_rag.ocr.service import get_ocr_service, init_ocr_service
from rbs_rag.services.scraper_service import ScraperService
from rbs_rag.models import StreamingChunk

log = logging.getLogger(__name__)

ROOT_DIR = Path(os.getenv("RAG_ROOT_DIR", ".rbs_rag")).resolve()
ADMIN_DB_PATH = ROOT_DIR / "admin.db"
TENANTS_DIR = ROOT_DIR / "tenants"

admin_store = AdminStore(ADMIN_DB_PATH)
ingestion_status: dict[str, dict[str, Any]] = {}
_scraper_service: ScraperService | None = None
_server_start_time = time.time()
_engine_cache: dict[str, RagEngine] = {}

TENANTS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TenBit RAG server starting")
    yield
    log.info("TenBit RAG server shutting down")
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

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# --- Rate Limiting ---
_rate_limit_store: dict[str, list[float]] = {}

def _check_rate_limit(client_ip: str, rpm: int = 60):
    now = time.time()
    window = 60.0
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if now - t < window]
    if len(_rate_limit_store[client_ip]) >= rpm:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_limit_store[client_ip].append(now)


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
    return {"status": "success", "token": token, "token_type": "Bearer"}


# --- Pydantic models ---
class TenantOnboardRequest(BaseModel):
    tenant_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    name: str
    subscription_tier: str = "basic"
    monthly_fee: float = 299.00
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_api_key: str
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
    name: str
    status: str = "active"
    subscription_tier: str = "basic"
    monthly_fee: float = 299.00
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_api_key: str
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
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed")
    if file_size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE // 1024 // 1024} MB)")


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
        storage=StorageConfig(provider="sqlite", path=str(TENANTS_DIR / tenant["tenant_id"] / "rag.db")),
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


def _log_to_ingestion(tenant_id: str, message: str, progress: int | None = None):
    if tenant_id not in ingestion_status:
        ingestion_status[tenant_id] = {"status": "idle", "logs": [], "progress": 0, "summary": None}
    ingestion_status[tenant_id]["logs"].append(message)
    if progress is not None:
        ingestion_status[tenant_id]["progress"] = progress


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

        db_path = Path(config.storage.path)
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                db_docs = conn.execute("SELECT document_id, name, path FROM documents").fetchall()
                for doc in db_docs:
                    doc_id = doc["document_id"]
                    if doc_id not in file_ids:
                        _log_to_ingestion(tenant_id, f"Cleaning up removed document '{doc['name']}'", 20)
                        conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                        conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                conn.commit()

        # Build set of already-ingested document IDs to skip duplicates
        already_ingested_ids = set()
        db_path = Path(config.storage.path)
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.execute("SELECT document_id FROM documents").fetchall()
                    already_ingested_ids = {r[0] for r in rows}
            except Exception:
                pass

        _log_to_ingestion(tenant_id, f"Found {len(files)} files ({len(already_ingested_ids)} already ingested).", 25)
        if not files:
            _log_to_ingestion(tenant_id, "No documents found. Index is clean.", 100)
            ingestion_status[tenant_id]["status"] = "completed"
            ingestion_status[tenant_id]["summary"] = {"documents": 0, "chunks": 0}
            return

        total_docs = 0
        total_chunks = 0
        skipped_docs = 0
        errors = []

        for idx, file_path in enumerate(files):
            if not file_path.is_file():
                continue
            progress_pct = int(25 + (idx / len(files)) * 70)

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
                source = "scrape" if "_scraped_" in file_path.name.lower() else "upload"
                source_url = document.metadata.get("source_url") if hasattr(document, "metadata") else None
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
        admin_store.log_activity(tenant_id=tenant_id, level="WARNING" if errors else "INFO", operation="INGESTION",
                                message=f"Ingestion {'completed with errors' if errors else 'successful'}: {total_docs} new docs, {total_chunks} chunks, {skipped_docs} skipped.",
                                details={"documents": total_docs, "chunks": total_chunks, "skipped": skipped_docs, "errors": errors})
    except Exception as exc:
        trace = traceback.format_exc()
        _log_to_ingestion(tenant_id, f"[Fatal] {exc}\n{trace}", 100)
        ingestion_status[tenant_id]["status"] = "error"
        ingestion_status[tenant_id]["summary"] = {"error": str(exc)}
        admin_store.log_activity(tenant_id=tenant_id, level="ERROR", operation="INGESTION", message=f"Fatal ingestion error: {exc}", traceback=trace)


# --- HTML pages ---

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    dashboard_file = static_dir / "index.html"
    if dashboard_file.exists():
        response = HTMLResponse(content=dashboard_file.read_text(encoding="utf-8"))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    return "<h3>Frontend index.html is still generating. Reload in a few seconds...</h3>"


@app.get("/client", response_class=HTMLResponse)
def get_client_dashboard():
    client_file = static_dir / "client.html"
    if client_file.exists():
        return HTMLResponse(content=client_file.read_text(encoding="utf-8"))
    return "<h3>Client dashboard is loading...</h3>"

@app.get("/widget", response_class=HTMLResponse)
def get_chat_widget():
    widget_file = static_dir / "widget.html"
    if widget_file.exists():
        return widget_file.read_text(encoding="utf-8")
    return "<h3>Frontend widget.html is still generating. Reload in a few seconds...</h3>"


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
        db_path = TENANTS_DIR / t["tenant_id"] / "rag.db"
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
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
        docs_dir = TENANTS_DIR / t["tenant_id"] / "documents"
        t["doc_count"] = len([x for x in docs_dir.glob("*") if x.is_file()]) if docs_dir.exists() else 0
        chunk_count = 0
        db_path = TENANTS_DIR / t["tenant_id"] / "rag.db"
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                    chunk_count = row[0] if row else 0
            except Exception:
                pass
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
    admin_store.upsert_tenant(tenant_data)
    tenant_dir = TENANTS_DIR / req.tenant_id
    (tenant_dir / "documents").mkdir(parents=True, exist_ok=True)
    ingestion_status[req.tenant_id] = {"status": "idle", "logs": ["Tenant created."], "progress": 0, "summary": None}
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


@app.put("/api/v1/tenants/{tenant_id}")
def update_tenant(tenant_id: str, req: TenantUpdateRequest, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    updated_data = req.model_dump()
    updated_data["tenant_id"] = tenant_id
    updated_data["api_key"] = tenant["api_key"]
    if req.llm_api_key == "***":
        updated_data["llm_api_key"] = tenant["llm_api_key"]
    if req.embedding_api_key == "***":
        updated_data["embedding_api_key"] = tenant.get("embedding_api_key") or ""
    admin_store.upsert_tenant(updated_data)
    if tenant_id in _engine_cache:
        del _engine_cache[tenant_id]
    return {"status": "success"}


@app.delete("/api/v1/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    admin_store.delete_tenant(tenant_id)
    tenant_dir = TENANTS_DIR / tenant_id
    if tenant_dir.exists():
        shutil.rmtree(tenant_dir)
    ingestion_status.pop(tenant_id, None)
    _engine_cache.pop(tenant_id, None)
    return {"status": "success"}


# --- TENANT DOCUMENTS APIs ---

@app.get("/api/v1/tenants/{tenant_id}/documents")
def list_tenant_documents(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    files_list = []
    # Read all ingested docs from DB for fast lookup
    ingested_map = {}
    doc_source_map = {}
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT document_id, name, source, source_url, ingested_at FROM documents").fetchall()
                for r in rows:
                    ingested_map[r["document_id"]] = r["name"]
                    doc_source_map[r["document_id"]] = {"source": r["source"], "source_url": r["source_url"], "ingested_at": r["ingested_at"]}
        except Exception:
            pass

    for item in docs_dir.glob("*"):
        if item.is_file():
            doc_id = _document_id(item)
            ingested = doc_id in ingested_map
            chunk_count = 0
            source_info = doc_source_map.get(doc_id, {"source": "upload", "source_url": None})
            # Count chunks if ingested
            if ingested and db_path.exists():
                try:
                    with sqlite3.connect(db_path) as conn:
                        row_chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)).fetchone()
                        chunk_count = row_chunks[0] if row_chunks else 0
                except Exception:
                    pass
            files_list.append({
                "name": item.name, "size_bytes": item.stat().st_size,
                "ingested": ingested, "chunks": chunk_count,
                "extension": item.suffix.lstrip("."),
                "source": source_info["source"],
                "source_url": source_info["source_url"],
                "ingested_at": source_info.get("ingested_at"),
            })
    return files_list


@app.get("/api/v1/tenants/{tenant_id}/documents/{filename}/chunks")
def get_document_chunks(tenant_id: str, filename: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
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
    file_path = TENANTS_DIR / tenant_id / "documents" / filename
    if file_path.exists():
        file_path.unlink()
    doc_id = _document_id(file_path)
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                conn.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database sync error: {e}")
    return {"status": "success"}


# --- INGESTION APIs ---

@app.post("/api/v1/tenants/{tenant_id}/ingest")
def trigger_ingestion(tenant_id: str, background_tasks: BackgroundTasks, apply_ocr: bool = Query(default=False), _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant_id in ingestion_status and ingestion_status[tenant_id]["status"] == "running":
        return {"status": "already_running"}
    ingestion_status[tenant_id] = {"status": "running", "logs": ["[System] Initiating ingestion."], "progress": 0, "summary": None}
    background_tasks.add_task(_run_ingestion_background, tenant_id, tenant, apply_ocr)
    already_ingested = 0
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if db_path.exists():
        try:
            with sqlite3.connect(str(db_path)) as conn:
                already_ingested = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        except Exception:
            pass
    return {"status": "started", "apply_ocr": apply_ocr, "already_ingested": already_ingested}


@app.get("/api/v1/tenants/{tenant_id}/ingest/status")
def get_ingestion_status(tenant_id: str, _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    status = ingestion_status.get(tenant_id, {"status": "idle", "logs": ["No ingestion tasks run yet."], "progress": 0, "summary": None})
    return status


# --- CHAT APIs ---

@app.post("/api/v1/tenants/{tenant_id}/chat")
async def chat_playground(tenant_id: str, req: ChatRequest, x_forwarded_for: str = Header("127.0.0.1"), _admin=Depends(require_admin)):
    _check_rate_limit(x_forwarded_for, 60)
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
    _check_rate_limit(x_forwarded_for, 30)
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
def chat_integration(req: ChatRequest, x_api_key: str = Header(..., alias="X-API-Key"), x_forwarded_for: str = Header("127.0.0.1")):
    _check_rate_limit(x_forwarded_for, 60)
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
    _check_rate_limit(x_forwarded_for, 30)
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
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    ingested_map = {}
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT document_id, name, source, source_url, ingested_at FROM documents").fetchall()
                for r in rows:
                    ingested_map[r["document_id"]] = r["name"]
        except Exception:
            pass
    files_list = []
    for item in docs_dir.glob("*"):
        if item.is_file():
            doc_id = _document_id(item)
            ingested = doc_id in ingested_map
            chunk_count = 0
            if ingested and db_path.exists():
                try:
                    with sqlite3.connect(db_path) as conn:
                        row_chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)).fetchone()
                        chunk_count = row_chunks[0] if row_chunks else 0
                except Exception:
                    pass
            files_list.append({
                "name": item.name, "size_bytes": item.stat().st_size,
                "ingested": ingested, "chunks": chunk_count,
                "extension": item.suffix.lstrip("."),
            })
    return files_list

@app.get("/api/v1/tenants/{tenant_id}/documents/{filename}")
def admin_get_document(tenant_id: str, filename: str, _admin=Depends(require_admin)):
    file_path = TENANTS_DIR / tenant_id / "documents" / filename
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
    file_path = TENANTS_DIR / tenant_id / "documents" / filename
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
        docs_dir = TENANTS_DIR / tenant_id / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        saved_files = []
        if job.crawl and job.results:
            for result in job.results:
                if result.is_success:
                    content = f"# {result.title}\n\nSource: {result.url}\n\n{result.content}"
                    safe_name = f"scraped_{uuid.uuid4().hex[:8]}.txt"
                    (docs_dir / safe_name).write_text(content, encoding="utf-8")
                    saved_files.append({"url": result.url, "file": safe_name, "title": result.title})
        elif job.result and job.result.is_success:
            content = f"# {job.result.title}\n\nSource: {job.result.url}\n\n{job.result.content}"
            safe_name = f"scraped_{uuid.uuid4().hex[:8]}.txt"
            (docs_dir / safe_name).write_text(content, encoding="utf-8")
            saved_files.append({"url": job.result.url, "file": safe_name, "title": job.result.title})
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if saved_files else "WARNING", operation="SCRAPE", message=f"Scraped {req.url}: {len(saved_files)} file(s)", details={"url": req.url, "files": saved_files})
        return {"status": "completed" if saved_files else "failed", "job_id": job.job_id, "url": req.url, "files_saved": len(saved_files), "files": saved_files, "error": job.error, "processing_time_ms": job.processing_time_ms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {e}")

@app.delete("/api/v1/client/documents/{filename}")
def client_delete_document(filename: str, tenant=Depends(_resolve_client_tenant)):
    tenant_id = tenant["tenant_id"]
    file_path = TENANTS_DIR / tenant_id / "documents" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    file_path.unlink()
    doc_id = _document_id(file_path)
    db_path = TENANTS_DIR / tenant_id / "rag.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE document_id = ?", (doc_id,))
                conn.commit()
        except Exception:
            pass
    return {"status": "deleted", "filename": filename}


# --- CLOUD SYNC, SCRAPE, OCR APIs ---

def _run_isolation_check():
    tenants = admin_store.list_tenants()
    results = []
    total_isolated = 0
    all_clean = True
    for t in tenants:
        tid = t["tenant_id"]
        t_dir = TENANTS_DIR / tid
        docs_dir = t_dir / "documents"
        db_path = t_dir / "rag.db"
        docs_exist = docs_dir.exists()
        db_exists = db_path.exists()
        db_clean = True
        doc_count = 0
        chunk_count = 0
        if db_exists:
            try:
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    foreign = conn.execute("SELECT COUNT(*) FROM chunks WHERE tenant_id != ?", (tid,)).fetchone()[0]
                    if foreign > 0:
                        db_clean = False
                        all_clean = False
                    doc_count = conn.execute("SELECT COUNT(*) FROM documents WHERE tenant_id = ?", (tid,)).fetchone()[0]
                    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE tenant_id = ?", (tid,)).fetchone()[0]
            except Exception:
                db_clean = False
        is_isolated = docs_exist and db_clean
        if is_isolated:
            total_isolated += 1
        results.append({"tenant_id": tid, "name": t["name"], "status": t["status"], "isolated": is_isolated, "doc_count": doc_count, "chunk_count": chunk_count})
    score = 100.0 if (len(tenants) == 0 or total_isolated == len(tenants)) else (total_isolated / len(tenants)) * 100.0
    return {"status": "verified" if all_clean else "warning", "score_percent": score, "total_tenants": len(tenants), "verified_isolated": total_isolated, "details": results}


@app.get("/api/v1/isolation-check")
def run_isolation_check(_admin=Depends(require_admin)):
    return _run_isolation_check()


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
        docs_dir = TENANTS_DIR / tenant_id / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        saved_files = []
        if job.crawl and job.results:
            for result in job.results:
                if result.is_success:
                    content = f"# {result.title}\n\nSource: {result.url}\n\n{result.content}"
                    safe_name = f"scraped_{uuid.uuid4().hex[:8]}.txt"
                    (docs_dir / safe_name).write_text(content, encoding="utf-8")
                    saved_files.append({"url": result.url, "file": safe_name, "title": result.title})
        elif job.result and job.result.is_success:
            content = f"# {job.result.title}\n\nSource: {job.result.url}\n\n{job.result.content}"
            safe_name = f"scraped_{uuid.uuid4().hex[:8]}.txt"
            (docs_dir / safe_name).write_text(content, encoding="utf-8")
            saved_files.append({"url": job.result.url, "file": safe_name, "title": job.result.title})
        admin_store.log_activity(tenant_id=tenant_id, level="INFO" if saved_files else "WARNING", operation="SCRAPE", message=f"Scraped {req.url}: {len(saved_files)} file(s)", details={"url": req.url, "files": saved_files})
        return {"status": "completed" if saved_files else "failed", "job_id": job.job_id, "url": req.url, "files_saved": len(saved_files), "files": saved_files, "error": job.error, "processing_time_ms": job.processing_time_ms}
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
    job = scraper.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post("/api/v1/tenants/{tenant_id}/ocr")
async def ocr_document(tenant_id: str, file: UploadFile = File(...), _admin=Depends(require_admin)):
    tenant = admin_store.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    docs_dir = TENANTS_DIR / tenant_id / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename).name
    target_path = docs_dir / filename
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
 