# Architecture — TenBit RAG Platform

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Clients                                       │
│            (Browser / Widget / curl / SDK)                              │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        nginx (Reverse Proxy)                            │
│                     Ports 80 (HTTP) / 443 (HTTPS)                       │
│                  Rate limiting, SSL termination, routing                 │
└────┬────────────┬──────────────┬──────────────────┬─────────────────────┘
     │            │              │                  │
     ▼            ▼              ▼                  ▼
┌─────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────────┐
│ RAG API │ │   OCR    │ │   Scraper    │ │   Static Assets  │
│(FastAPI)│ │ Service  │ │   Service    │ │   (React SPA)    │
│ :8000   │ │ :8000    │ │ :8000        │ │   /assets/*      │
└────┬────┘ └──────────┘ └──────┬───────┘ └──────────────────┘
     │                          │
     ▼                          ▼
┌──────────────┐       ┌───────────────┐
│    Redis     │       │    Qdrant     │
│  (Cache+QL)  │       │ (Vector DB)   │
│  :6379       │       │ :6333/:6334   │
└──────┬───────┘       └───────┬───────┘
       │                       │
       ▼                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           SQLite (per-tenant)                            │
│            /data/.rbs_rag/admin.db  +  /data/.rbs_rag/tenants/*/rag.db  │
│              Tenants, Documents, Chunks, Sessions, Activity Log           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Service Breakdown

### 1. RAG API (`src/rbs_rag/`)

**Purpose:** Core retrieval-augmented generation engine with multi-tenant admin.

| Aspect | Detail |
|---|---|
| **Framework** | FastAPI (Python 3.11) |
| **Entry Point** | `src/rbs_rag/web/server.py` |
| **Port** | 8000 (internal) |
| **Key Modules** | `engine.py` (orchestrator), `retrieval.py` (hybrid search), `llm.py` (LLM clients), `embeddings.py` (embedding providers), `chunking.py` (text splitting), `cache.py` (Redis client) |

**Responsibilities:**
- Multi-tenant CRUD (tenants, documents, sessions)
- Document ingestion pipeline (extract → chunk → embed → store)
- Hybrid search retrieval (dense + sparse) with reranking
- LLM query/chat (Gemini, OpenAI, Anthropic, Ollama)
- SSE streaming chat
- Web scraping orchestration
- Cloud sync (Google Drive, OneDrive, S3, Confluence)
- Admin authentication (JWT) + client auth (API keys)
- Prometheus metrics
- Serve React SPA frontend

### 2. OCR Service (`ocr-service-main/`)

**Purpose:** Document text extraction from images and PDFs.

| Aspect | Detail |
|---|---|
| **Framework** | FastAPI (Python 3.11) |
| **Entry Point** | `ocr-service-main/main.py` |
| **Port** | 8000 |
| **Engines** | PaddleOCR (local), Mistral OCR API, Nemotron (NVIDIA NIM) |

**Responsibilities:**
- Image OCR (`POST /ocr/image`)
- PDF OCR (`POST /ocr/pdf`)
- Batch OCR (`POST /ocr/batch`)
- Benchmarking (`/benchmark`)
- Rate-limited via `slowapi`

### 3. Scraper Service (`scraper-service/`)

**Purpose:** Web scraping with headless browser support.

| Aspect | Detail |
|---|---|
| **Framework** | FastAPI (Python 3.11) |
| **Entry Point** | `scraper-service/app/main.py` |
| **Port** | 8000 |
| **Tools** | Playwright, Selenium, crawl4ai, BeautifulSoup |

**Responsibilities:**
- Single-page scrape (`/scrape/`)
- Recursive crawl (`/crawl/recursive`)
- Full-site crawl with images + PDFs (`/crawl/full`)
- WordPress REST API scraping
- Redis-backed cache & job queue (optional via `REDIS_ENABLED`)

### 4. Frontend (`chic-interface-design/`)

**Purpose:** Admin dashboard + client workspace + embeddable widget.

| Aspect | Detail |
|---|---|
| **Framework** | React 19 + TanStack Router + Tailwind CSS |
| **Build** | Vite (`vite.spa.config.ts` → `dist-spa/`) |
| **Served By** | Python backend (static files from `dist-spa/`) |
| **API Base** | `/api/v1` (same origin, no CORS in production) |

**Key Routes:**
- `/` — Admin dashboard (tenant management, ingestion, playground)
- `/client` — Client workspace (chat, documents, ingestion)
- `/login` — Login page
- `/widget` — Widget embed tester

### 5. Qdrant (Vector Database)

**Purpose:** ANN (Approximate Nearest Neighbor) search for document embeddings.

| Aspect | Detail |
|---|---|
| **Image** | `qdrant/qdrant:latest` |
| **Ports** | 6333 (REST), 6334 (gRPC) |
| **Collection** | `rag_chunks` |
| **Distance** | Cosine |
| **Dimensions** | 384 (configurable) |

**Graceful Degradation:** If Qdrant is unavailable, search falls back to BM25 over SQLite chunks.

### 6. Redis (Cache & Queue)

**Purpose:** Distributed caching, rate limiting, ingestion status persistence.

| Aspect | Detail |
|---|---|
| **Image** | `redis:7-alpine` |
| **Port** | 6379 |
| **Persistence** | AOF (append-only file) |

**Techniques Used:**

| Data Structure | Use Case | Key Pattern | TTL |
|---|---|---|---|
| **Sorted Set** | Rate limiting (sliding window) | `rate_limit:{client_ip}` | 60s |
| **Hash** | Ingestion status persistence | `ingestion:{tenant_id}` | 3600s |
| **String** | Scraper cache | `scraper_cache:{url_hash}` | 300s |
| **String** | Job store | `scraper_job:{job_id}` | 86400s |
| **String** | Chat session hot cache | `session:{tenant_id}:{session_id}` | 1800s |
| **List** | Crawl job queue (future) | `scraper_queue` | — |

**Graceful Degradation:** All Redis operations wrapped in try-catch. If Redis is down:
- Rate limiting → allows all requests (no false 429s)
- Ingestion status → in-memory fallback
- Cache → cache miss (re-fetches from source)
- Jobs → in-memory job store fallback

---

## Data Flow

### Document Upload → Answer

```
1. Upload        POST /api/v1/tenants/{id}/documents
                    │
2. Ingest        POST /api/v1/tenants/{id}/ingest
                    │
3. Extract       load_document() → text (via OCR if image/PDF)
                    │
4. Chunk         HierarchicalChunker → overlapping token windows
                    │
5. Embed         EmbeddingProvider → vector (384d float[])
                    │
6. Store         SQLite (metadata) + Qdrant (vectors)
                    │
7. Query         POST /api/v1/tenants/{id}/chat
                    │
8. Retrieve      HybridRetriever: Qdrant ANN + BM25 (SQLite) + RRF fusion
                    │
9. Rerank        Cross-encoder (BGE) or Local (term overlap)
                    │
10. Generate     LLM (Gemini/OpenAI/Anthropic) with context + citations
                    │
11. Respond      Answer with citations + validation scores
```

### Ingestion Status Flow (Redis-backed)

```
request          ┌─────────────┐
  │              │   Redis     │
  ├─Trigger─────▶│ INGESTION   │────▶ Background Task
  │              │ {tenant_id} │        │
  │              └─────────────┘        │
  │                                     ▼
  ├─Poll────────▶ ingestion_status      Extract → Chunk → Embed → Store
  │              (in-memory + Redis)        │
  │                                         ▼
  │              ┌─────────────┐       Update Redis
  └─Response────▶│ Status:     │◀────── via _log_to_ingestion()
                 │ Progress:95%│       + _sync_ingestion_to_redis()
                 │ Complete    │
                 └─────────────┘
```

---

## Multi-Tenant Isolation

```
/data/.rbs_rag/
├── admin.db                    # Global admin: tenants, activity logs
└── tenants/
    └── {tenant_id}/
        ├── documents/           # Uploaded files
        ├── rag.db               # Per-tenant SQLite: docs, chunks, sessions
        └── config.json          # Per-tenant LLM/embedding/retrieval config
```

- Each tenant has **isolated SQLite database**
- Qdrant collections filter by `tenant_id` payload
- Documents are stored in per-tenant directories
- API keys are tenant-scoped (hashed + encrypted via Fernet)

---

## Frontend-Backend Integration

```
┌──────────┐         ┌──────────┐         ┌──────────┐
│  Browser │────────▶│  nginx   │────────▶│  RAG API │
│  React   │         │  :80     │         │  :8000   │
│  SPA     │         │          │         │          │
│          │         │          │         │ /api/v1/*│
│ index.html─────────▶──────────▶─────────▶  chat    │
│ style.css──────────▶──────────▶─────────▶  ingest  │
│ app.js─────────────▶──────────▶─────────▶  admin   │
│          │         │          │         │          │
│          │◀────────│◀─────────│◀────────│ index.html│
└──────────┘         └──────────┘         └──────────┘
```

- **Development:** Vite dev server proxies `/api` → `http://127.0.0.1:3001`
- **Production:** Python backend serves static SPA files. All API calls on same origin.
- **Streaming:** SSE via `POST /api/v1/chat/stream` — nginx configured with `proxy_buffering off`
- **Auth:** Admin uses Bearer JWT, clients use `X-API-Key` header

---

## Redis Client Architecture

```python
# src/rbs_rag/cache.py
RedisClient
├── __init__()          → Initializes both async + sync connections
│                          Graceful: if Redis down, _enabled = False
│
├── Async Methods (a- prefix)
│   ├── asliding_window() → Rate limiting (Sorted Set + pipeline)
│   ├── aget_json()       → Cache read
│   ├── aset_json()       → Cache write with TTL
│   ├── ahset/ahget/ahgetall/ahdel/aexpire → Hash operations
│   └── ...               → All wrapped in try-catch
│
├── Sync Methods (s- prefix)
│   ├── sget_json/sset_json  → For BackgroundTasks (sync context)
│   ├── shset/shgetall       → Ingestion persistence
│   └── sdelete              → Cleanup on tenant delete
│
└── close()             → Clean shutdown (both connections)
```

**Why both sync and async?**
- Request handlers are async (FastAPI) → use `a-` methods
- Background tasks are sync (BackgroundTasks) → use `s-` methods
- Same interface, different implementations

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Python backend, not Node.js** | Richer ML/AI ecosystem (PaddleOCR, fastembed, transformers). CLI tool (`rag` command) |
| **SQLite per tenant** | Zero operational overhead. No PostgreSQL needed. Each tenant isolated |
| **Redis for rate limiting** | Distributed sliding window works across containers. In-memory fallback safe |
| **React SPA served by backend** | No CORS issues. Single deployable unit. Simplified nginx config |
| **Graceful degradation everywhere** | System runs even if Qdrant/Redis is down. No SPOF |
| **Hybrid search (dense + sparse)** | Better retrieval quality than pure vector search. BM25 catches exact matches |
