# Comprehensive Production-Grade Architecture Analysis — TenBit RAG Platform

> **Generated:** 2025 | **Version:** 1.0 | **Status:** Complete Analysis

---

## Executive Summary

This document provides a **comprehensive, critical analysis** of the TenBit RAG platform architecture, comparing the current implementation against the enterprise-grade architecture defined in the [RAG Architecture Specification](.rbs_rag/tenants/testing-gdrive/documents/rag.md). It identifies every gap, technical debt, architectural flaw, and improvement opportunity needed to achieve a production-grade, enterprise-ready RAG system.

---

## 1. Current Architecture Overview

### 1.1 System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TENBIT RAG PLATFORM                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   RAG Core      │  │   OCR Service   │  │  Scraper Service│             │
│  │   (src/rbs_rag) │  │ (ocr-service-   │  │ (scraper-service│             │
│  │                 │  │  main)          │  │  -main)         │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                      │
│           └────────────────────┼────────────────────┘                      │
│                                │                                          │
│                    ┌───────────▼───────────┐                              │
│                    │    React Dashboard    │                              │
│                    │   (src/rbs_rag/web/   │                              │
│                    │   static/index.html)  │                              │
│                    └───────────┬───────────┘                              │
│                                │                                          │
│                    ┌───────────▼───────────┐                              │
│                    │   Multi-Tenant Data   │                              │
│                    │   (.rbs_rag/tenants/)  │                              │
│                    └───────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Current Technology Stack

| Layer | Technology | Status |
|-------|------------|--------|
| **Vector Storage** | SQLite (JSON-serialized embeddings) | ❌ Not Production-Grade |
| **Embeddings** | Hash Embeddings (deterministic, non-semantic) | ❌ Not Production-Grade |
| **Reranking** | Lexical word-overlap heuristic | ❌ Not Production-Grade |
| **Chunking** | Hierarchical + Token Boundary | ✅ Implemented |
| **Search** | Dense + Sparse (BM25) + RRF Fusion | 🟡 Python loops (O(n)) |
| **OCR** | Not integrated | ❌ Missing |
| **Web Scraping** | Not integrated | ❌ Missing |
| **Token Streaming** | Synchronous only | ❌ Missing |
| **Multi-Tenancy** | SQLite per tenant | ✅ Implemented |
| **API Layer** | FastAPI (sync endpoints) | 🟡 Partially async |
| **Frontend** | Vanilla JS + HTML (single page) | 🟡 Basic |
| **Auth** | API Key only (no JWT/OAuth) | ⚠️ Basic |
| **Observability** | Basic logging | ⚠️ Minimal |

---

## 2. Gap Analysis: Target vs Current Architecture

### 2.1 RAG Document Target Architecture

From the [architecture specification](.rbs_rag/tenants/testing-gdrive/documents/rag.md):

```
INGESTION PIPELINE:
Document Upload → Document Parsing → OCR Processing → Metadata Extraction 
→ Metadata Enrichment → Hierarchical Chunking → Semantic Chunking 
→ Token Boundary Enforcement → Embedding Generation → Index Creation 
→ Vector Database Storage

RETRIEVAL PIPELINE:
User Query → Metadata Filtering → Dense Retrieval → Sparse Retrieval 
→ Hybrid Search Fusion → Cross-Encoder Reranker → Context Assembly → LLM

SEARCH STRATEGY: Dense + Sparse + Metadata Filtering = Hybrid Search

RERANKING: BGE Reranker (Cross-Encoder)

MEMORY: Session Memory + User Memory

VALIDATION: Self-RAG (Evidence Verification, Retrieval Sufficiency, 
Grounding Verification, Answer Confidence Assessment)

RESPONSE: Context Assembly → Prompt Construction → LLM Generation 
→ Citation Generation → Token Streaming → Final Response
```

### 2.2 Critical Gaps Matrix

| # | Architecture Layer | Target (RAG Doc) | Current Implementation | Gap Severity | Impact |
|---|---|---|---|---|---|
| **1** | **Vector Database** | Qdrant (HNSW, ANN, Hybrid Search) | SQLite + JSON embeddings + O(n) brute force | 🔴 **CRITICAL** | Cannot scale past ~5K chunks; 30-60s latency at 100K |
| **2** | **Embeddings** | BGE-M3 (Dense + Sparse + Multi-vector) | Hash embeddings (non-semantic) | 🔴 **CRITICAL** | Zero semantic understanding; "car" ≠ "vehicle" |
| **3** | **Reranker** | BGE Reranker (Cross-Encoder) | Word-overlap heuristic | 🔴 **CRITICAL** | Lexical only; misses semantic relevance |
| **4** | **Semantic Chunking** | Semantic boundary detection | Heading-based only | 🟠 **HIGH** | Topic splits mid-chunk; poor retrieval quality |
| **5** | **OCR Processing** | Required for scanned PDFs/images | Not implemented | 🟠 **HIGH** | Cannot process scanned documents |
| **6** | **Token Streaming** | SSE streaming for LLM responses | Synchronous full response | 🟠 **HIGH** | 10-50s wait time; terrible UX |
| **7** | **Metadata Enrichment** | 20+ fields (Author, Date, Language, etc.) | 3 fields only | 🟡 **MEDIUM** | Limited filtering; poor retrieval precision |
| **8** | **Hybrid Search** | Native (Qdrant built-in) | Python loops (O(n)) | 🟠 **HIGH** | Slow, no hardware acceleration |
| **9** | **Self-RAG Validation** | 4 responsibilities | Basic score thresholds | 🟡 **MEDIUM** | No grounding verification; hallucination risk |
| **10** | **Async Architecture** | Fully async (httpx, connection pools) | Sync urllib, no pooling | 🟠 **HIGH** | Blocks threads; single request per worker |
| **11** | **Security** | Encrypted keys, auth, rate limiting | Plaintext keys, no CORS, no auth | 🔴 **CRITICAL** | Production security vulnerability |
| **12** | **Observability** | Health checks, metrics, tracing | Basic logging | 🟡 **MEDIUM** | No production monitoring |

---

## 3. Detailed Technical Analysis by Module

### 3.1 Vector Storage (store.py) — 🔴 CRITICAL

**Current Implementation:**
```python
# store.py line 50
embedding_json TEXT NOT NULL  # "[0.123, -0.456, ...]" as JSON text
```

**Problems:**
1. **No Vector Index** — Every query loads ALL chunks from SQLite into Python memory
2. **JSON Parsing Overhead** — Embeddings stored as text strings, parsed per query
3. **O(n) Brute Force** — Cosine similarity computed in Python `for` loop
4. **No SIMD/AVX** — No hardware acceleration
5. **Memory Explosion** — Loads entire dataset per query; OOM at scale

**Scaling Characteristics:**
| Chunks | Search Latency | Status |
|--------|----------------|--------|
| 100 | ~50ms | OK |
| 1,000 | ~200-400ms | Noticeable |
| 10,000 | ~2-5s | Slow |
| 100,000 | ~30-60s | Unusable |
| 1,000,000 | Crashes (OOM) | ☠️ |

**Required: Qdrant Migration**
- HNSW index with quantization → sub-10ms search
- Native hybrid search (dense + sparse vectors)
- Per-tenant collections for isolation
- Embedded (dev) + Server (prod) modes

---

### 3.2 Embeddings (embeddings.py) — 🔴 CRITICAL

**Current: HashEmbeddingProvider**
```python
# Deterministic hash of tokens → NOT SEMANTIC
# "Annual Revenue" and "Yearly Income" = completely different vectors
```

**Problems:**
1. **Zero Semantic Understanding** — Cannot capture meaning, synonyms, context
2. **No Dense/Sparse Vectors** — BGE-M3 provides both natively
3. **Production Unsuitable** — Only for dev/testing

**Required: BGE-M3 Integration**
```python
# Tiered embedding options:
# 1. Local BGE-M3 (best quality, ~1.5GB model, GPU/CPU)
# 2. Cloud Embeddings (OpenAI/Gemini — already supported)
# 3. Hash Embeddings (dev-mode fallback only)
```

---

### 3.3 Reranking (reranking.py) — 🔴 CRITICAL

**Current: LocalReranker (Lexical Heuristic)**
```python
# Word overlap ratio + phrase match bonus
# "car" vs "vehicle" = 0 overlap score
```

**Problems:**
1. **No Cross-Encoder** — Not a learned ranking model
2. **Pure String Matching** — Misses semantic relevance
3. **RAG Doc Explicitly Recommends BGE Reranker**

**Required: BGE Reranker (Cross-Encoder)**
- Scores (query, chunk) pairs with trained model
- Local fallback for environments without GPU

---

### 3.4 Document Loaders (document_loaders.py) — 🟠 HIGH

**Current: Basic text extraction only**
- No OCR fallback for scanned PDFs
- No image extraction from PDFs
- Minimal metadata (name, type, path only)

**OCR Service Available But Not Integrated:**
- `/projects/TenBit/RAG/ocr-service-main/` — Full OCR microservice
- Mistral OCR (primary) + PaddleOCR (fallback)
- Hybrid PDF pipeline (native text + OCR for scanned pages)
- Rich output: Markdown, HTML tables, entities

**Required: OCR Integration Pipeline**
```
Document Upload
    ↓
Try native text extraction (PyMuPDF)
    ↓
If text < MIN_TEXT_CHARS_THRESHOLD → OCR via ocr-service-main
    ↓
Merge results → Continue to chunking
```

---

### 3.5 Chunking (chunking.py) — 🟡 PARTIAL

**Current: HierarchicalChunker**
- Splits by markdown headings (H1-H6)
- Token window with overlap (320/48 default)
- No semantic boundary detection

**Missing: Semantic Chunking**
- Paragraph-level embedding similarity analysis
- Topic shift detection within sections
- Pipeline: Hierarchical → Semantic → Token Boundary

---

### 3.6 Retrieval (retrieval.py) — 🟠 HIGH

**Current: Python Loops**
```python
# Loads ALL chunks every query
chunks = self.store.list_chunks(...)

# Pure Python cosine similarity
dense_scores = {chunk.chunk_id: cosine_similarity(query_emb, chunk.embedding)
                for chunk in chunks}
```

**Problems:**
1. O(n) scan every query
2. No ANN index
3. No connection pooling
4. Synchronous only

---

### 3.7 LLM Layer (llm.py) — 🟠 HIGH

**Current: Synchronous urllib**
```python
# urllib.request.urlopen — BLOCKING
# No streaming, no async, no connection pooling
```

**Missing: Token Streaming (SSE)**
- All providers support `stream=True`
- Frontend receives tokens in real-time
- Keep non-streaming for widget/API integration

---

### 3.8 Web Server (server.py) — 🟠 HIGH

**Issues:**
1. **Sync endpoints** — Blocks during LLM generation (10-50s)
2. **No connection pooling** — SQLite/Qdrant connections per request
3. **Engine recreation** — `RagEngine` instantiated per request
4. **No rate limiting** — Single tenant can exhaust API quota
5. **Terminal endpoint** — Arbitrary command execution (security risk)
6. **Plaintext API keys** — Stored in SQLite unencrypted
7. **No CORS config** — Wide open
8. **No admin auth** — Dashboard accessible without auth

---

### 3.9 OCR Service (ocr-service-main) — ✅ PRODUCTION-READY

**Architecture: Pluggable Strategy Pattern**
```
OCROrchestrator → MistralOCREngine (primary) → PaddleOCREngine (fallback)
```

**Capabilities:**
- Images: PNG, JPEG, WEBP, BMP, TIFF
- PDFs: Digital + Scanned (hybrid pipeline)
- Batch processing (API + CLI)
- Rich output: Markdown, HTML tables, entities
- Rate limiting, API key auth, CORS, health endpoint
- Structured JSON logging, request tracing

**API Endpoints:**
- `POST /ocr/image` — Single image
- `POST /ocr/pdf` — Single PDF
- `POST /ocr/batch` — Multiple files
- `GET /health` — Engine availability

---

### 3.10 Scraper Service (scraper-service-main) — ✅ PRODUCTION-READY

**Architecture: Modular Pipeline**
```
Fetch → Detect → Parse → Extract → Format
```

**Capabilities:**
- Recursive web crawling (multi-depth, queue-based)
- Content type detection (HTML, PDF, images, videos, Office docs)
- Detectors: Login wall, Cloudflare, Captcha, JS-required
- Facebook post/reel scraping (3 auth methods)
- Media proxy with DASH merge (ffmpeg)
- SQLite storage with Excel export
- Profile scraping (7 platforms)
- Retry system with exponential backoff
- In-memory TTL cache (Redis-ready)

**API Endpoints:**
- `POST /crawl` — Single page
- `POST /crawl/recursive` — Full site crawl
- `POST /scrape/fb-posts` — Facebook posts (async job)
- `POST /scrape/profile` — Profile scraper
- `GET /proxy/media` — Media streaming
- `GET /db/*` — Storage management

---

## 4. Integration Architecture: OCR + Scraper into RAG

### 4.1 Document Ingestion Pipeline (Enhanced)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ENHANCED INGESTION PIPELINE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Document Upload                                                             │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                   │
│  │   Source    │────►│  Document   │────►│  Metadata   │                   │
│  │  Detection  │     │   Parsing   │     │ Extraction  │                   │
│  └─────────────┘     └──────┬──────┘     └─────────────┘                   │
│                             │                                              │
│              ┌──────────────┼──────────────┐                              │
│              ▼              ▼              ▼                              │
│       ┌─────────────┐ ┌───────────┐ ┌─────────────┐                       │
│       │  Text-Based │ │   PDF     │ │  Image/     │                       │
│       │  (MD, TXT,  │ │  (Digital │ │  Scanned    │                       │
│       │   DOCX)     │ │   Text)   │ │  (OCR)      │                       │
│       └──────┬──────┘ └─────┬─────┘ └──────┬──────┘                       │
│              │              │              │                              │
│              └──────────────┼──────────────┘                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │  OCR Service    │                                    │
│                    │  (Fallback)     │                                    │
│                    │  POST /ocr/pdf  │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ Metadata        │                                    │
│                    │ Enrichment      │                                    │
│                    │ (20+ fields)    │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ Hierarchical    │                                    │
│                    │ Chunking        │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ Semantic        │                                    │
│                    │ Chunking        │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ Token Boundary  │                                    │
│                    │ Enforcement     │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ BGE-M3          │                                    │
│                    │ Embeddings      │                                    │
│                    │ (Dense+Sparse)  │                                    │
│                    └────────┬────────┘                                    │
│                             │                                              │
│                             ▼                                              │
│                    ┌─────────────────┐                                    │
│                    │ Qdrant Vector   │                                    │
│                    │ Storage         │                                    │
│                    │ (Per-Tenant)    │                                    │
│                    └─────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Scraper Integration Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SCRAPER INTEGRATION PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  User Provides URLs (Dashboard UI)                                          │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────┐                                                    │
│  │  Scraper Service    │                                                    │
│  │  POST /crawl/       │                                                    │
│  │  recursive          │                                                    │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  Crawl Job          │                                                    │
│  │  (Background)       │                                                    │
│  │  - Progress polling │                                                    │
│  │  - Content detection│                                                    │
│  │  - PDF extraction   │                                                    │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐     ┌─────────────────┐                           │
│  │  Extracted Content  │────►│  OCR Service    │ (if PDFs scanned)         │
│  │  (HTML, PDF, etc.)  │     │  POST /ocr/pdf  │                           │
│  └──────────┬──────────┘     └─────────────────┘                           │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  Markdown/JSON      │                                                    │
│  │  Formatter Output   │                                                    │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  RAG Ingestion      │                                                    │
│  │  (Same pipeline)    │                                                    │
│  └─────────────────────┘                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Production-Grade Improvement Plan

### 5.1 Phase 1: Vector Infrastructure (CRITICAL — Foundation)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **1.1** Add Qdrant config & client abstraction | `config.py`, `vector_store.py` (new) | 4h | qdrant-client |
| **1.2** Migrate chunk storage to Qdrant collections | `store.py`, `retrieval.py`, `engine.py` | 8h | 1.1 |
| **1.3** Add BGE-M3 embedding provider | `embeddings.py`, `config.py` | 6h | sentence-transformers/FlagEmbedding |
| **1.4** Update ingestion to write to Qdrant | `server.py`, `document_loaders.py` | 4h | 1.2 |
| **1.5** Support embedded Qdrant (dev) + server (prod) | `vector_store.py`, `config.py` | 4h | 1.1 |

**Total Phase 1: ~26 hours**

---

### 5.2 Phase 2: Retrieval Quality (CRITICAL — Accuracy)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **2.1** Add BGE Reranker (Cross-Encoder) | `reranking.py`, `config.py` | 6h | sentence-transformers/FlagEmbedding |
| **2.2** Implement Semantic Chunking | `chunking.py` | 8h | embeddings (for similarity) |
| **2.3** Optimize hybrid search with Qdrant native | `retrieval.py` | 4h | 1.2 |
| **2.4** Add metadata filtering to Qdrant queries | `retrieval.py`, `vector_store.py` | 4h | 1.2 |

**Total Phase 2: ~22 hours**

---

### 5.3 Phase 3: Streaming & UX (HIGH — User Experience)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **3.1** Add SSE streaming endpoint | `server.py`, `llm.py` | 6h | httpx (async) |
| **3.2** Make LLM clients async with httpx | `llm.py` | 6h | httpx |
| **3.3** Add connection pooling & engine caching | `server.py`, `engine.py` | 4h | 3.2 |
| **3.4** Update frontend for streaming | `static/index.html` | 4h | 3.1 |

**Total Phase 3: ~20 hours**

---

### 5.4 Phase 4: Data Pipeline Integration (HIGH — Completeness)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **4.1** Integrate OCR service into document loaders | `document_loaders.py` | 6h | ocr-service-main API |
| **4.2** Add scraper service client & endpoints | `server.py` (new endpoints) | 6h | scraper-service-main API |
| **4.3** Enrich metadata extraction (20+ fields) | `document_loaders.py`, `chunking.py` | 8h | - |
| **4.4** Add web UI for OCR/Scraper status | `static/index.html` | 6h | 4.1, 4.2 |

**Total Phase 4: ~26 hours**

---

### 5.5 Phase 5: Reliability & Validation (MEDIUM — Quality)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **5.1** Enhance Self-RAG validation | `validation.py`, `engine.py` | 8h | - |
| **5.2** Add rate limiting per tenant | `server.py`, `admin_db.py` | 4h | - |
| **5.3** Add exponential backoff for LLM retries | `llm.py` | 4h | - |
| **5.4** Add request queuing | `server.py` | 4h | 3.3 |

**Total Phase 5: ~20 hours**

---

### 5.6 Phase 6: Security Hardening (CRITICAL — Production)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **6.1** Encrypt API keys at rest (AES-256) | `admin_db.py`, `config.py` | 4h | cryptography |
| **6.2** Add prompt injection detection | `server.py`, `engine.py` | 4h | - |
| **6.3** Restrict/remove terminal endpoint | `server.py` | 2h | - |
| **6.4** Add CORS middleware config | `server.py` | 2h | - |
| **6.5** Add admin authentication (JWT) | `server.py`, `admin_db.py` | 6h | pyjwt |
| **6.6** Add session ID validation | `server.py`, `models.py` | 2h | - |

**Total Phase 6: ~20 hours**

---

### 5.7 Phase 7: Observability & Polish (MEDIUM — Operations)

| Task | Files | Effort | Dependencies |
|------|-------|--------|--------------|
| **7.1** Add health/ready/metrics endpoints | `server.py` | 4h | prometheus-client |
| **7.2** Add structured logging with correlation IDs | `server.py`, all modules | 4h | python-json-logger |
| **7.3** Add document deduplication | `document_loaders.py`, `server.py` | 4h | - |
| **7.4** Add chunk-level caching | `embeddings.py`, `retrieval.py` | 4h | - |
| **7.5** Support more document formats | `document_loaders.py` | 6h | python-docx, openpyxl, etc. |

**Total Phase 7: ~22 hours**

---

## 6. Estimated Total Effort

| Phase | Hours | Priority |
|-------|-------|----------|
| Phase 1: Vector Infrastructure | 26 | 🔴 CRITICAL |
| Phase 2: Retrieval Quality | 22 | 🔴 CRITICAL |
| Phase 3: Streaming & UX | 20 | 🟠 HIGH |
| Phase 4: Data Pipeline Integration | 26 | 🟠 HIGH |
| Phase 5: Reliability & Validation | 20 | 🟡 MEDIUM |
| Phase 6: Security Hardening | 20 | 🔴 CRITICAL |
| Phase 7: Observability & Polish | 22 | 🟡 MEDIUM |
| **TOTAL** | **~156 hours** | |

---

## 7. Architecture Decision Records (ADRs)

### ADR-001: Vector Database Selection — Qdrant
**Status:** Accepted
**Decision:** Use Qdrant for vector storage
**Rationale:** Native hybrid search (dense+sparse), per-tenant collections, excellent performance at scale, simple deployment (single binary/Docker)
**Alternatives Considered:** ChromaDB (embedded, no hybrid search), Milvus (too complex), Weaviate (heavier)

### ADR-002: Embedding Model — BGE-M3 Local
**Status:** Accepted
**Decision:** Use BGE-M3 locally via FlagEmbedding/sentence-transformers
**Rationale:** Dense + sparse + multi-vector natively, no per-query API costs, matches RAG doc recommendation, multilingual support
**Alternatives Considered:** OpenAI/Gemini cloud (latency + cost), Jina v4 (newer, less proven)

### ADR-003: Reranker — BGE Cross-Encoder Local
**Status:** Accepted
**Decision:** Use BGE Reranker locally
**Rationale:** Cross-encoder architecture, learns semantic relevance, matches RAG doc, no API costs
**Alternatives Considered:** Cloud reranking APIs, Cohere (paid), keep heuristic (not production)

### ADR-004: OCR Integration — HTTP Client to ocr-service-main
**Status:** Accepted
**Decision:** Call ocr-service-main via HTTP from document_loaders.py
**Rationale:** Separate microservice, already production-ready, pluggable engines, fallback support
**Alternatives Considered:** Embed PaddleOCR directly (more deps, less features), Mistral only (no fallback)

### ADR-005: Scraper Integration — HTTP Client to scraper-service-main
**Status:** Accepted
**Decision:** Call scraper-service-main via HTTP for URL ingestion
**Rationale:** Separate microservice, handles complex crawling/auth, already production-ready
**Alternatives Considered:** Embed crawling logic (reinventing wheel), simple requests (no JS rendering, no auth)

### ADR-006: Token Streaming — SSE (Server-Sent Events)
**Status:** Accepted
**Decision:** Use SSE for LLM token streaming
**Rationale:** Simple, native browser support, works over HTTP/1.1, no WebSocket complexity
**Alternatives Considered:** WebSockets (overkill), polling (inefficient), no streaming (poor UX)

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Qdrant migration breaks existing data | Medium | High | Thorough testing, migration scripts, backup strategy |
| BGE-M3 model download fails in prod | Low | High | Pre-bundle model, fallback to cloud embeddings |
| OCR service unavailable | Medium | Medium | Local PaddleOCR fallback, graceful degradation |
| Scraper blocked by target sites | High | Medium | DeepCrawl fallback, rate limiting, proxy rotation |
| Token streaming breaks widget/API | Low | Medium | Keep non-streaming endpoint, feature flag |
| Security audit findings | High | Critical | Phase 6 first, penetration testing |
| Performance regression at scale | Medium | High | Load testing, benchmarking at each phase |

---

## 9. Success Criteria for Production-Grade

### 9.1 Performance Targets
- [ ] Vector search: <10ms p99 at 100K chunks
- [ ] End-to-end query: <2s p99 (including LLM)
- [ ] Token streaming: First token <500ms
- [ ] Ingestion: >100 pages/minute
- [ ] Concurrent users: 100+ per tenant

### 9.2 Accuracy Targets
- [ ] Retrieval recall@10: >90%
- [ ] Reranker precision@5: >85%
- [ ] Grounding confidence: >95% High/No Hallucination
- [ ] Citation accuracy: 100% verifiable

### 9.3 Reliability Targets
- [ ] Uptime: 99.9%
- [ ] Error rate: <0.1%
- [ ] Recovery time: <30s
- [ ] Data durability: 99.9999%

### 9.4 Security Targets
- [ ] API keys encrypted at rest
- [ ] All endpoints authenticated
- [ ] Rate limiting enforced
- [ ] Audit logging for all operations
- [ ] Penetration test passed

---

## 10. Next Steps

1. **Review & Prioritize** — Confirm phase ordering with stakeholders
2. **Environment Setup** — Provision Qdrant (embedded for dev, server for prod)
3. **Phase 1 Kickoff** — Start Qdrant migration + BGE-M3 integration
4. **Parallel Track** — Integrate OCR & Scraper services (Phase 4)
5. **Security First** — Begin Phase 6 immediately (can run in parallel)
6. **Continuous Validation** — Automated tests at each phase gate

---

## Appendix: File Inventory

### Core RAG Files (to modify)
```
/projects/TenBit/RAG/src/rbs_rag/
├── config.py              # Add Qdrant, BGE-M3, Reranker, Streaming config
├── embeddings.py          # Add BGE-M3 provider
├── reranking.py           # Add BGE Cross-Encoder
├── chunking.py            # Add Semantic Chunking
├── document_loaders.py    # Add OCR + Metadata Enrichment
├── retrieval.py           # Qdrant queries, hybrid search
├── store.py               # Split: relational + vector store
├── vector_store.py        # NEW: Qdrant abstraction
├── validation.py          # Enhanced Self-RAG
├── engine.py              # Engine caching, async init
├── llm.py                 # Async httpx, streaming
├── models.py              # Updated schemas
├── web/
│   ├── server.py          # Async endpoints, auth, rate limiting
│   └── static/index.html  # Streaming UI, OCR/Scraper tabs
├── web_run.py             # Port 8100
└── pyproject.toml         # New dependencies
```

### OCR Service (to integrate via HTTP)
```
/projects/TenBit/RAG/ocr-service-main/
├── api/routers/ocr.py     # POST /ocr/image, /ocr/pdf, /ocr/batch
├── main.py                # FastAPI app (port 8000)
└── schemas/ocr.py         # OCRResult, PageResult schemas
```

### Scraper Service (to integrate via HTTP)
```
/projects/TenBit/RAG/scraper-service-main/
├── app/main.py            # FastAPI app (port 8000)
├── app/api/routes/
│   ├── crawl.py           # POST /crawl, /crawl/recursive
│   ├── scrape.py          # POST /scrape/fb-posts, /scrape/profile
│   └── storage.py         # GET /db/*
└── app/schemas/           # Request/Response models
```

---

*End of Analysis Document*