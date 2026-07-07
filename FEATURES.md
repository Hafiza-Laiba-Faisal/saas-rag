# RBS RAG Multi-Tenant SaaS Platform Features

This document details the capabilities and core architecture of the RBS RAG platform. This engine platform with integrated OCR and Web Scraping services. The engine scales from a single enterprise deployment to a multi-tenant commercial SaaS product without requiring a redesign of the underlying ingestion or retrieval paths.

---

## 1. Core Architecture Integrations

Our platform integrates all architectural layers requested in your specification:

| Layer | Capabilities & Implementation |
| :--- | :--- |
| **Hybrid Search** | Melds **Dense Vector Search** (via Cosine Similarity over embeddings) and **Sparse Search** (via BM25 term frequency) using Reciprocal Rank Fusion (RRF) with configurable weightings. |
| **Metadata-Aware** | Every document chunk carries Tenant ID, Knowledge Base ID, Page/Section Headings, Document Type, and custom labels. Queries are isolated and filtered using strict metadata matching. |
| **Hierarchical Chunking** | Avoids simple character boundaries. It parses document headings (H1–H6) to segment text into logical structural nodes, maintaining parent context and mapping structural sections. |
| **Semantic Formatting** | Groups paragraphs by reading structure, maintaining heading prefixes (e.g. `[1] Document / Section / Paragraph`) to preserve contextual alignment during LLM generation. |
| **Token-Boundary Enforcement** | Restricts chunk sizes to strict token limits (default `320` tokens max, `48` tokens overlap) to optimize LLM context window efficiency. |
| **Reranking Layer** | Features a local **Cross-Encoder style reranking** heuristic that scores word overlapping and phrase matches to rank candidates and keep context size optimal. |
| **Session Memory** | Automatically updates and appends conversational turns (history context) to queries to handle follow-up intents. |
| **User Memory** | Stores customer details (e.g., Roles, Department, Preferences) and references them during prompt construction. |
| **Self-RAG Validation** | Heuristically analyzes retrieved context, flags grounding confidence (High, Medium, Low), checks if context is sufficient, and informs the frontend playground. |
| **Agentic Integration** | Generates secure API keys (`rbs_rag_sk_...`) and pre-built integration widget scripts for embedding the chatbot on third-party web pages. |

---

## 2. Integrated Services Architecture

### 2.1 OCR Service (Intelligent Document Processing)

The OCR Service is a production-ready microservice built on FastAPI with a pluggable engine architecture:

| Feature | Implementation |
|---------|---------------|
| **Pluggable Engine Architecture** | Strategy Pattern with `MistralOCREngine` (primary, cloud) → `PaddleOCREngine` (fallback, local) |
| **File Format Support** | Images (PNG, JPEG, WEBP, BMP, TIFF), PDFs (digital & scanned), Batch processing |
| **Rich Structured Output** | Full text, Markdown, HTML tables, hyperlinks, paragraphs/lines/words, bounding boxes, entities (URLs, emails, phones) |
| **Hybrid PDF Pipeline** | Native text extraction for digital PDFs → OCR only for scanned pages (configurable threshold) |
| **Intelligent Preprocessing** | Grayscale, binarization, noise reduction, contrast enhancement, dynamic upscaling for low-DPI |
| **Advanced Table Extraction** | HTML format with merged cells, nested headers, multi-column layout support |
| **Entity Extraction** | Auto-extract URLs, emails, phone numbers from all OCR output |
| **Production-Grade API** | Rate limiting (60 req/min/IP), API key auth, CORS, request logging, health checks, file size limits |
| **Observability** | Structured JSON logging, per-request tracing (X-Request-ID), timing metrics, Sentry integration |

**Integration with RAG Pipeline:**
- Documents that fail text extraction (scanned PDFs, images) automatically route to OCR service
- OCR results (text, markdown, tables) feed directly into hierarchical chunking pipeline
- Processing status visible in Document tab of React dashboard

### 2.2 Web Scraper Service (Intelligent Content Ingestion)

The Scraper Service is a production-ready web scraping platform with recursive crawling:

| Feature | Implementation |
|---------|---------------|
| **Recursive Web Crawling** | Queue-based scheduling, depth control, domain filtering, robots.txt compliance, sitemap discovery |
| **Content Type Detection** | HTML, PDF, Images, Videos, Office docs, Archives, JSON/XML with automatic routing |
| **Intelligent Processing** | Deduplication, query param filtering, redirect handling, error tracking, progress callbacks |
| **Background Jobs** | Thread-safe job store (50 concurrent), real-time stats (pages/sec, content distribution) |
| **Single Page Crawl** | 6-stage pipeline: Fetch → Detect → Parse → Extract → Format → Respond |
| **Facebook Scraper** | Posts & Reels with JSON blob extraction, Selenium DOM fallback, DASH manifest parsing for video |
| **Profile Scraper** | 7 platforms: Instagram/Twitter (API), Facebook/Reddit/GitHub/TikTok/Pinterest (Selenium) |
| **Media Proxy** | CORS bypass for Facebook CDN, DASH video+audio merge via ffmpeg |
| **SQLite Storage** | Sessions, posts, reels with full-text search, filtering, pagination |
| **Excel Export** | Embedded images (160×160), hyperlinked URLs, frozen headers, streaming response |

**Integration with RAG Pipeline:**
- Users submit URLs via dashboard → Scraper extracts content → Ingested into RAG
- Recursive crawls for entire documentation sites
- Scraped content follows same chunking/embedding pipeline as uploaded documents
- Job status and progress visible in dashboard

---

## 3. Multi-Tenant SaaS Architecture

```
Global Admin Store (admin.db)
       ↓
       ├─► Client A Workspace (tenants/client-a/)
       │      ├── Documents Folder (PDF, DOCX, MD, HTML)
       │      └── Isolated DB Index (rag.db) [Gemini API Key]
       │
       └─► Client B Workspace (tenants/client-b/)
              ├── Documents Folder (PDF, DOCX, MD, HTML)
              └── Isolated DB Index (rag.db) [OpenAI / Anthropic API Key]
```

### Complete Database & File Isolation
- **Global Settings (admin.db)**: Tracks client metadata (onboarding date, billing tier, fees, active/suspended status), custom LLM keys, and RAG tuning parameters.
- **Isolated Client Database (rag.db)**: Located in `tenants/{tenant_id}/rag.db`. Contains only the client's documents, chunks, session turns, and user memory. Connection pools are separate.
- **Isolated Storage Folder**: Located in `tenants/{tenant_id}/documents/`. Physical document files are saved in separate directories.
- **API Key & Endpoint Isolation**: A client makes calls to `/api/v1/chat` using their header `X-API-Key`. The request resolves the client, opens their database, calls their configured LLM endpoint, and queries only their index.

---

## 3. Supported Integrations

### LLM Providers
1. **Gemini** (Google API key, supports custom fallback models).
2. **OpenAI / OpenAI-Compatible** (supports OpenAI, Groq, OpenRouter, Together, Fireworks).
3. **Anthropic** (Claude models, converts system roles to Anthropic's top-level system parameter).

### Embedding Providers
1. **Local Deterministic Hash**: Extremely fast, zero-service baseline (384 dimensions).
2. **sentence-transformers (BGE)**: Local open-source models via `sentence-transformers` library (e.g. `BAAI/bge-small-en-v1.5`, 384 dim). Fully offline, zero-cost.
3. **OpenAI Cloud Embeddings** (`text-embedding-3-small` or large, 1536 dimensions).
4. **Gemini Cloud Embeddings** (`text-embedding-004`, 768 dimensions).
5. **BGE-M3 Local** (Planned) — Dense + Sparse + Multi-vector natively, ~1.5GB model, multilingual support.

---

## 4. Production-Grade Architecture (Target State)

The following enhancements are required to achieve enterprise production-grade readiness:

### 4.1 Vector Database Migration — Qdrant
| Current (SQLite) | Target (Qdrant) |
|-----------------|-----------------|
| O(n) brute-force scan | HNSW ANN index (<10ms search) |
| JSON-serialized embeddings | Native vector storage + quantization |
| No hardware acceleration | SIMD/AVX optimized |
| Single-threaded | Concurrent connections + connection pooling |
| ~5K chunks max | 1M+ chunks per tenant |

**Implementation:** Create `vector_store.py` abstraction, migrate chunk storage, keep SQLite for relational data (sessions, metadata, audit).

### 4.2 Semantic Embeddings — BGE-M3
| Current (sentence-transformers) | Target (BGE-M3) |
|--------------------------------|-----------------|
| sentence-transformers (BGE models) | Dense + Sparse + Multi-vector |
| Basic semantic search | "Revenue" ≈ "Income" |
| 384 dim (configurable) | 1024 dim dense + sparse |
| Local inference | Production-grade |

### 4.3 Cross-Encoder Reranking — BGE Reranker
| Current (Heuristic) | Target (Cross-Encoder) |
|--------------------|------------------------|
| Word overlap scoring | Learned semantic relevance |
| "car" vs "vehicle" = 0 | "car" vs "vehicle" = high |
| No training signal | Trained on relevance pairs |

### 4.4 Token Streaming — SSE
| Current (Sync) | Target (Streaming) |
|---------------|-------------------|
| 10-50s full wait | First token <500ms |
| Blocking threads | Async httpx + SSE |
| Poor UX | Real-time token display |

### 4.5 Semantic Chunking
| Current (Hierarchical) | Target (Hierarchical + Semantic) |
|----------------------|----------------------------------|
| Heading-based only | Heading + paragraph similarity boundaries |
| Topic splits mid-chunk | Topic-aware boundaries |
| Fixed token windows | Adaptive semantic windows |

### 4.6 Metadata Enrichment (20+ Fields)
| Current (3 fields) | Target (20+ fields) |
|-------------------|---------------------|
| name, type, path | Tenant ID, KB ID, Doc ID, Name, Type, Department, Country, Region, Language, Author, Version, Creation Date, Modification Date, Upload Date, Page Number, Section, Subsection, Tags, Access Level |

### 4.7 Enhanced Self-RAG Validation
| Current (Basic) | Target (Complete) |
|----------------|------------------|
| Score thresholds only | Evidence verification |
| | Retrieval sufficiency check |
| | Grounding verification |
| | Answer confidence assessment |

---

## 5. Deployment Architecture

### 5.1 Service Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRODUCTION DEPLOYMENT                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Load       │    │   React      │    │   FastAPI    │                   │
│  │   Balancer   │───►│   Dashboard  │───►│   (Port 8100)│                   │
│  │   (nginx)    │    │   (Static)   │    │   RAG API    │                   │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                   │
│                                                 │                           │
│              ┌──────────────────────────────────┼───────────────────────┐  │
│              │                                  │                       │  │
│              ▼                                  ▼                       ▼  │
│       ┌───────────────┐              ┌─────────────────┐       ┌─────────────────┐
│       │   Qdrant      │              │   OCR Service   │       │  Scraper        │
│       │   (Vector DB) │              │   (Port 8001)   │       │  Service        │
│       │   Port 6333   │              │   - Mistral OCR │       │  (Port 8002)    │
│       │               │              │   - PaddleOCR   │       │  - Recursive    │
│       │   Collections │              │   - Hybrid PDF  │       │    Crawl        │
│       │   per Tenant  │              │   - Batch API   │       │  - FB Scraper   │
│       └───────────────┘              └─────────────────┘       │  - Media Proxy  │
│                                                                    └─────────────────┘
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        SHARED INFRASTRUCTURE                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │ │
│  │  │   Redis      │  │  PostgreSQL  │  │  Prometheus  │  │   Grafana  │  │ │
│  │  │   (Cache,    │  │  (Admin DB,  │  │  (Metrics)   │  │  (Dash-    │  │ │
│  │  │   Sessions,  │  │   Tenant     │  │              │  │   boards)  │  │ │
│  │  │   Rate Limit)│  │   Config)    │  │              │  │            │  │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Development Mode (Current)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEVELOPMENT MODE                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  React Dashboard (Port 8100)                                                │
│       │                                                                      │
│       ▼                                                                      │
│  FastAPI RAG API (Port 8100) ◄──────────────────────────────────────────┐   │
│       │                                                                  │   │
│       ├──► SQLite (admin.db + per-tenant rag.db)                         │   │
│       ├──► Embedded Qdrant (in-memory) ◄─── For vector search           │   │
│       ├──► OCR Service (Port 8001) ◄──────────────────────────────────┐  │   │
│       │       - Mistral OCR (cloud)                                    │  │   │
│       │       - PaddleOCR (local fallback)                             │  │   │
│       │                                                                  │  │   │
│       └──► Scraper Service (Port 8002) ◄──────────────────────────────┘  │   │
│               - Recursive crawl                                          │   │
│               - Facebook scraper                                         │   │
│               - Media proxy                                              │   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Security Architecture

### 6.1 Multi-Layer Security

| Layer | Implementation |
|-------|---------------|
| **Transport** | TLS 1.3 (production), HTTPS enforcement |
| **Authentication** | API Keys (tenant), JWT (admin), OAuth 2.0 (planned) |
| **Authorization** | Tenant isolation at DB + Vector level |
| **Data at Rest** | AES-256 encryption for API keys (planned) |
| **Input Validation** | Pydantic v2 on all endpoints |
| **Rate Limiting** | Per-tenant configurable (by subscription tier) |
| **Audit Logging** | All admin actions, ingestion, queries logged |

### 6.2 Tenant Isolation Guarantees

```
Request: POST /api/v1/chat
Headers: X-API-Key: rbs_rag_sk_tenantA_xxx

1. API Key Validation → Resolves to Tenant ID: "tenantA"
2. Database Connection → Opens: tenants/tenantA/rag.db
3. Qdrant Collection → Queries: "tenantA_chunks"
4. LLM Call → Uses: tenantA's configured provider + key
5. Response → Only tenantA's data accessible
```

---

## 7. Observability & Operations

### 7.1 Health Endpoints
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe (DB, Qdrant, OCR, Scraper connectivity)
- `GET /metrics` — Prometheus metrics

### 7.2 Key Metrics
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Query latency (p99) | <2s | >5s |
| Vector search latency (p99) | <10ms | >50ms |
| Ingestion throughput | >100 pages/min | <20 pages/min |
| Error rate | <0.1% | >1% |
| Token streaming first-byte | <500ms | >2s |

### 7.3 Distributed Tracing
- Request ID propagation across all services
- Structured JSON logging with correlation IDs
- OpenTelemetry integration (planned)

---

## 8. API Reference Summary

### 8.1 RAG Core API (Port 8100)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/tenants` | POST | Onboard new tenant |
| `/api/v1/tenants/{id}` | GET/PUT/DELETE | Manage tenant |
| `/api/v1/tenants/{id}/documents` | POST | Upload document |
| `/api/v1/tenants/{id}/documents` | GET | List documents |
| `/api/v1/tenants/{id}/ingest` | POST | Trigger ingestion |
| `/api/v1/tenants/{id}/chat` | POST | Chat (sync) |
| `/api/v1/tenants/{id}/chat/stream` | POST | Chat (SSE streaming) |
| `/api/v1/tenants/{id}/search` | POST | Search without LLM |
| `/api/v1/tenants/{id}/sessions` | GET/POST/DELETE | Chat sessions |
| `/api/v1/tenants/{id}/cloud-sync` | POST | Sync from Google Drive/OneDrive |

### 8.2 OCR Service API (Port 8001)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ocr/image` | POST | OCR single image |
| `/ocr/pdf` | POST | OCR single PDF |
| `/ocr/batch` | POST | Batch OCR multiple files |
| `/health` | GET | Health check + engine status |

### 8.3 Scraper Service API (Port 8002)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/crawl` | POST | Single page crawl |
| `/crawl/test` | GET | Quick test crawl |
| `/crawl/crawl/recursive` | POST | Start recursive site crawl |
| `/crawl/recursive/status/{job_id}` | GET | Poll crawl progress |
| `/scrape/fb-posts` | POST | Start Facebook scrape job |
| `/scrape/fb-posts/status/{job_id}` | GET | Poll FB scrape progress |
| `/scrape/profile` | POST | Scrape social profile |
| `/proxy/media` | GET | Stream Facebook CDN media |
| `/db/sessions` | GET | List scrape sessions |
| `/db/posts` | GET | Query scraped posts |
| `/db/export/excel` | GET | Export to Excel |

---

*End of Features Document*
