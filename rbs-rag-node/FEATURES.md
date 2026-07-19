# RBS RAG Node.js — Features

## Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Node.js 22+ (TypeScript, ESM) |
| Web Framework | Express.js |
| ORM | Prisma (SQLite) |
| Vector DB | Qdrant (HNSW ANN, cosine distance) |
| Cache | Redis (optional, rate limiting) |
| Security | Helmet, CORS, JWT, bcrypt |

---

## 1. Core RAG Pipeline

### Hybrid Search (Dense + Sparse + RRF)
- **Dense Vector Search**: Query embedded via configured `EmbeddingProvider`, searched in Qdrant using cosine distance (up to `topK * 2` candidates)
- **Fallback (SQLite)**: If Qdrant returns zero results, chunks fetched from SQLite store with local cosine similarity computation
- **Sparse Search**: BM25 scores computed with k1=1.5, b=0.75 across all candidate chunks (`text.ts`)
- **RRF Fusion**: Dense and sparse scores converted to reciprocal ranks, fused via configurable weights (default `0.55` dense / `0.45` sparse)

### Retrieval Pipeline (5-Phase)

| Phase | Component | Description |
|---|---|---|
| 1 | Embed Query | `EmbeddingProvider.embed([query])` |
| 2 | Qdrant ANN Search | Top `topK * 2` candidates by cosine distance |
| 3 | BM25 Sparse Scoring | Term-frequency scoring across all candidates |
| 4 | RRF Fusion | `score = denseWeight * denseRank + sparseWeight * sparseRank` |
| 5 | Rerank | `LocalReranker` (query-term overlap + phrase bonus) → `finalContextK` results |

### Hierarchical Chunking
- Parses Markdown headings (`H1`-`H6`) to segment text into logical structural sections
- Sliding token windows within each section (default `320` tokens max, `48` tokens overlap)
- Heading-aware metadata: each chunk carries section context, document name, tenant ID, KB ID

### Document Support
- `.txt`, `.md`, `.html`, `.csv`, `.pdf` (via `pdf-parse`)
- Office docs handled by external OCR service
- Scraped web pages saved as `.txt` files

---

## 2. Supported Providers

### LLM Providers

| Provider | SDK / Method | Models |
|---|---|---|
| **Gemini** | `@google/generative-ai` | `gemini-2.5-flash-lite`, `gemini-2.5-pro`, etc. |
| **OpenAI / Compatible** | `fetch` → `/v1/chat/completions` | GPT-4o, GPT-4, GPT-3.5, Groq, OpenRouter, Together |
| **Anthropic** | `fetch` → `api.anthropic.com` | Claude 3.5 Sonnet, Claude 3 Opus, etc. |
| **Mistral** | OpenAI-compatible client | `mistral-large`, etc. |
| **Ollama** | OpenAI-compatible base URL | Any local model |

Key features:
- Auto-detection by API key prefix or URL pattern
- Fallback chain: primary model → `fallbackModels` on 429/503/UNAVAILABLE
- SSE streaming via async generators (`generateStream`)
- Response cleaning: strips HTML tags, broken tags, normalizes whitespace

### Embedding Providers

| Provider | Dimensions | Type |
|---|---|---|
| **HashEmbedding** | 384 (default) | Local, deterministic, SHA-256 based, no API key |
| **OpenAI** | 1536 (`text-embedding-3-small`) | Cloud API |
| **Gemini** | 768 (`text-embedding-004`) | Cloud API |

---

## 3. Multi-Tenant SaaS

### Tenant Isolation Model

```
admin.db (Prisma SQLite)
  └── tenants table: tenantId, apiKey, llmProvider, llmApiKey, 
      per-tenant retrieval/chunking/embedding config

tenants/{tenantId}/
  ├── documents/     # Isolated file storage
  └── rag.db         # Per-tenant documents, chunks, sessions
```

### Per-Tenant Configuration
Each tenant stores independent:
- LLM provider, model, API key, base URL
- Embedding provider, model, dimensions
- Retrieval params (topK, dense/sparse weights, rerank)
- Chunking params (max tokens, overlap, semantic)
- System prompt, session memory limit, chat retention

### Tenant CRUD via Admin API
- `POST /api/v1/tenants` — Onboard with auto-generated API key (`rbs_rag_sk_<hex>`)
- `GET /tenants` / `GET /tenants/:id` / `PUT /tenants/:id` / `DELETE /tenants/:id`
- Cascading delete: sessions → chunks → documents → activity logs → tenant

---

## 4. Web Scraper (`scraper.ts`)

| Feature | Implementation |
|---|---|
| **Validation** | Blocks private/internal networks (localhost, 10.x, 172.16-31.x, 192.168.x, etc.) |
| **Fetch** | Native `fetch` with browser-like headers + Cloudflare bypass via `curl` fallback |
| **Content Extraction** | `cheerio` — smart article selectors (`article`, `main`, `.content`, `.post`, etc.) |
| **WordPress Support** | REST API fallback with shortcode stripping, JSON-LD extraction |
| **Recursive Crawl** | BFS queue, domain filtering, depth/pages limit, deduplication |
| **Full Site Mode** | Sitemap discovery → language variant detection → parallel crawl |
| **Output** | Saved as `{site}_{title}_{type}_{jobId}.txt` in tenant documents dir |

### Scrape Parameters
| Param | Default | Description |
|---|---|---|
| `url` | — | Target URL |
| `crawl` | `false` | Follow same-domain links |
| `full_site` | `false` | Smart sitemap + language detection + deep crawl |
| `max_pages` | `10` (crawl) / `50` (full_site) | Max pages to fetch |
| `max_depth` | `1` (crawl) / `3` (full_site) | Link depth limit |

---

## 5. Cloud Sync

| Provider | Method |
|---|---|
| **Direct URL** | `fetch` → save as document |
| **Google Drive** | Public file ID or share link → download |
| **OneDrive** | Direct download URL |

All downloaded files are saved to `tenants/{tenantId}/documents/` and can be auto-ingested.

---

## 6. Session Memory & Chat

- Per-session conversation history stored in SQLite `session_turns`
- Configurable memory limit (default 8 turns)
- Auto-purge after configurable retention days (default 30)
- Session memory injected into LLM context during chat
- SSE streaming for both admin and client endpoints

### Chat Endpoints
| Endpoint | Auth | Type |
|---|---|---|
| `POST /api/v1/tenants/:id/chat` | JWT (admin) | Sync |
| `POST /api/v1/tenants/:id/chat/stream` | JWT (admin) | SSE Streaming |
| `POST /api/v1/chat` | X-API-Key (client) | Sync |
| `POST /api/v1/chat/stream` | X-API-Key (client) | SSE Streaming |

---

## 7. Validation & Observability

### Retrieval Validation (`validation.ts`)
- Confidence scoring (High / Medium / Low) based on dense + sparse + rerank scores
- Context sufficiency check
- Answers include citation metadata (document name, section, chunk ID)

### System Observability
| Endpoint | Description |
|---|---|
| `GET /api/v1/health` | Server health (status, DB, version, uptime) |
| `GET /api/v1/system/status` | Tenant counts, document/chunk totals |
| `GET /api/v1/system/logs` | Activity logs with filtering |
| `GET /api/v1/isolation-check` | Multi-tenant isolation audit |

### Activity Logging
All operations (tenant create/delete, ingest, scrape, cloud sync, admin login) logged to `activity_logs` table with level, operation, message, details JSON, and traceback.

---

## 8. API Endpoints Summary

### Admin Endpoints (JWT Bearer)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/admin/login` | Auth (username/password → JWT) |
| GET/POST | `/api/v1/tenants` | List / Create tenants |
| GET/PUT/DELETE | `/api/v1/tenants/:id` | Tenant CRUD |
| GET/POST/DELETE | `/api/v1/tenants/:id/documents` | Document management |
| POST | `/api/v1/tenants/:id/ingest` | Start ingestion |
| GET | `/api/v1/tenants/:id/ingest/status` | Ingestion progress |
| POST | `/api/v1/tenants/:id/chat` | Chat (sync) |
| POST | `/api/v1/tenants/:id/chat/stream` | Chat (SSE streaming) |
| POST | `/api/v1/tenants/:id/scrape` | Scrape URL |
| POST | `/api/v1/tenants/:id/cloud-sync` | Cloud sync |
| GET/DELETE | `/api/v1/tenants/:id/sessions` | Session management |
| GET | `/api/v1/system/status` | System overview |
| GET | `/api/v1/system/logs` | Activity logs |
| GET | `/api/v1/isolation-check` | Isolation audit |
| POST | `/api/v1/terminal/exec` | Terminal commands |

### Client Endpoints (X-API-Key)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/chat` | Chat with KB |
| POST | `/api/v1/chat/stream` | SSE streaming chat |
| GET/POST/DELETE | `/api/v1/client/documents` | Document management |
| POST | `/api/v1/client/ingest` | Trigger ingestion |
| GET | `/api/v1/client/ingest/status` | Ingestion status |
| POST | `/api/v1/client/scrape` | Scrape URL |

---

## 9. Qdrant Integration

- Collection: `rag_chunks` with configurable vector size (default 384) and COSINE distance
- Payload metadata: `chunk_id`, `document_id`, `text`, `ordinal`, tenant fields
- Batch upserts in groups of 64
- **Graceful degradation**: All Qdrant operations wrapped in try-catch; if unavailable, system falls back to SQLite-only retrieval
- UUID v5 point IDs for deterministic mapping

---

## 10. Security

| Layer | Implementation |
|---|---|
| **Transport** | Helmet headers, CORS configuration |
| **Authentication** | JWT (admin), API key `rbs_rag_sk_*` (client) |
| **Authorization** | Tenant isolation at DB + file + Qdrant level |
| **Input Validation** | TypeScript types, Express JSON parsing |
| **Rate Limiting** | `express-rate-limit` (configurable RPM) |
| **Audit Logging** | All admin operations logged to `activity_logs` |
| **Private Network** | Scraper blocks localhost, RFC 1918, link-local addresses |
