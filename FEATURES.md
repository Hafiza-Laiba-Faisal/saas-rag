# Features — TenBit RAG Platform

## 1. Document Management

### Supported File Types

| Category | Formats |
|---|---|
| Text | `.txt`, `.md`, `.html`, `.htm`, `.rtf`, `.json`, `.xml`, `.csv` |
| PDF | `.pdf` (text + OCR for scanned) |
| Office | `.docx`, `.pptx`, `.xlsx`, `.doc`, `.ppt`, `.xls` |
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.svg` |

**Max upload size:** 100 MB per file.

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/tenants/{id}/documents` | List documents (with ingest status, chunk count) |
| `POST` | `/api/v1/tenants/{id}/documents` | Upload one or more files |
| `GET` | `/api/v1/tenants/{id}/documents/{file}` | Download file |
| `DELETE` | `/api/v1/tenants/{id}/documents/{file}` | Delete file + cleanup chunks |
| `GET` | `/api/v1/tenants/{id}/documents/{file}/chunks` | View extracted chunks |

### Client API (API Key Auth)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/client/documents` | List documents |
| `POST` | `/api/v1/client/documents` | Upload documents |
| `GET` | `/api/v1/client/documents/{file}` | Download |
| `DELETE` | `/api/v1/client/documents/{file}` | Delete |

---

## 2. Ingestion Pipeline

### Flow

```
Upload → Load Document (text extraction) → Chunk → Embed → Store (SQLite + Qdrant)
```

- **Text Extraction:** `documentLoaders.py` handles each file type. PDFs can use OCR via the OCR service (`?apply_ocr=true`)
- **Chunking:** `HierarchicalChunker` splits by headings → sliding token windows with overlap
  - Configurable: `max_tokens` (default 320), `overlap_tokens` (default 48), `semantic_chunking` (optional)
- **Embedding:** Multiple providers:
  - `hash` — Deterministic zero-dependency (dev/testing)
  - `fastembed` — Local BGE models (production, no API key)
  - `openai` — `text-embedding-3-small`
  - `gemini` — Gemini embedding models
  - `mistral` — Mistral embedding models
- **Storage:** Metadata in per-tenant SQLite + vectors in shared Qdrant collection (filtered by `tenant_id`)

### API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/tenants/{id}/ingest` | Start ingestion (`?apply_ocr=true` for scanned docs) |
| `GET` | `/api/v1/tenants/{id}/ingest/status` | Poll status (progress %, logs, summary) |

**Status persistence:** Ingestion progress is stored in Redis (key `ingestion:{tenant_id}`). Survives server restarts.

### Ingestion Status Redis Schema

```json
{
  "status": "running|completed|error",
  "logs": ["[OK] file.pdf: extracted 5000 chars.", ...],
  "progress": 75,
  "summary": {
    "documents": 5,
    "chunks": 42,
    "skipped": 2,
    "errors": ["corrupt.pdf: PDF syntax error"]
  }
}
```

---

## 3. Retrieval-Augmented Generation (RAG)

### Hybrid Search

Combines two retrieval methods with Reciprocal Rank Fusion (RRF):

```python
# Dense search (Qdrant)
vector = embed(query)
qdrant_results = qdrant.search(vector, limit=top_k)

# Sparse search (SQLite BM25)
bm25_scores = bm25(query, all_chunks)
sparse_results = rank_by_bm25(bm25_scores, limit=top_k)

# Fusion
combined = rrf_fusion(dense_results, sparse_results)
# weights: dense=0.55, sparse=0.45 (configurable)

# Rerank
reranked = cross_encoder.rerank(query, combined[:rerank_top_k])
```

### Reranking

| Reranker | Type | Description |
|---|---|---|
| `local` | Term overlap | Fast, no dependencies. Scores by query-term overlap + phrase bonus |
| `bge_cross_encoder` | Cross-encoder | BAAI/bge-reranker-v2-m3 — higher quality, requires transformers |

### Configuration

| Parameter | Default | Description |
|---|---|---|
| `top_k` | 20 | Initial retrieval |
| `rerank_top_k` | 8 | Passed to reranker |
| `final_context_k` | 5 | Top chunks sent to LLM |
| `dense_weight` | 0.55 | Dense search weight in RRF |
| `sparse_weight` | 0.45 | Sparse search weight |

### Validation

Each answer includes a validation report:

```json
{
  "sufficient": true,
  "confidence": "high",
  "confidence_score": 0.87,
  "reasons": [
    "Found 4 relevant chunks (threshold: 3)",
    "High citation-text alignment (cosine: 0.91)"
  ]
}
```

---

## 4. Chat / Query

### Modes

| Mode | Endpoint | Description |
|---|---|---|
| Sync | `POST /api/v1/tenants/{id}/chat` | Non-streaming. Returns full answer |
| Stream (SSE) | `POST /api/v1/tenants/{id}/chat/stream` | Server-Sent Events. Real-time token streaming |
| Client Sync | `POST /api/v1/chat` | Via `X-API-Key` header |
| Client Stream | `POST /api/v1/chat/stream` | Via `X-API-Key` header |

### SSE Format

```
data: {"text": "Based on the documents", "done": false}

data: {"text": " the answer is...", "done": false}

data: {"text": " the answer is 42.", "done": true, "citations": [{"index": 1, "document_name": "report.pdf", "chunk_id": "abc123"}]}
```

### LLM Providers

| Provider | SDK | Models |
|---|---|---|
| **Gemini** | `@google/generative-ai` | gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash |
| **OpenAI** | `openai` or direct HTTP | gpt-4o, gpt-4o-mini, gpt-3.5-turbo |
| **Anthropic** | `@anthropic-ai/sdk` | claude-3-opus, claude-3-sonnet, claude-3-haiku |
| **Mistral** | HTTP | mistral-small-latest, mistral-medium-latest, mistral-large-latest |
| **NVIDIA NIM** | HTTP | meta/llama-3.1-8b-instruct, meta/llama-3.1-70b-instruct, mistralai/mistral-7b-instruct-v03 |
| **OpenRouter** | HTTP | Any supported provider (GPT-4o, Claude, Llama, etc.) |
| **Ollama** | HTTP | Any local model (llama3, mistral, etc.) |

### Conversation Context

Each turn saves:
- User query + LLM answer in SQLite (`SessionTurn`)
- Previous turns included as chat history (up to `session_memory_limit`)
- Sessions auto-expire after `chat_retention_days`

---

## 5. Web Scraping

### Modes

| Mode | Endpoint | Description |
|---|---|---|
| Single page | `POST /api/v1/tenants/{id}/scrape` | Scrape one URL |
| Enhanced | `POST /api/v1/scrape/enhanced` | Smart/recursive/WordPress/full-site via scraper service |
| Recursive crawl | `POST /api/v1/scrape/enhanced` with `crawl=true` | Multi-page crawl with depth control |
| Full-site | `POST /api/v1/scrape/enhanced` with `full_site=true` | Complete site including images, PDFs, all subpages |

### Scraper Service Backend

```
Request → Scraper Service
           ├── Playwright (JS-rendered pages)
           ├── Selenium (alternative browser)
           ├── BeautifulSoup (simple HTML)
           ├── WordPress REST API (WordPress sites)
           ├── crawl4ai (deep crawling)
           └── Cloudscraper (Cloudflare bypass)
```

### Output

Scraped pages saved as `scraped_{uuid}.txt` in tenant's documents directory:
```
# Title
Source: https://example.com/page

Full extracted text content...
```

### Redis Cache for Scraping

When `REDIS_ENABLED=true`:
- Scraped pages cached with 5-minute TTL (`scraper_cache:{url_hash}`)
- Avoids re-crawling same URLs during recursive/full crawls
- Job store persisted in Redis (`scraper_job:{job_id}`, 24h TTL)
- Survives scraper service restarts

### Facebook Post Scraper

Scrapes posts and reels from any Facebook page:
- Extracts captions, media URLs, post URLs, like/comment counts, timestamps
- Primary: JSON blob extraction from page source (3 strategies)
- Fallback: Selenium DOM extraction via JavaScript
- DASH manifest parsing for reels — separate video + audio URLs
- Date range filtering (`date_from` / `date_to`)
- Configurable `max_posts` and `scroll_rounds`

**Endpoints:**
```
POST /scrape/fb-posts          Start Facebook scrape (returns job_id)
GET  /scrape/fb-posts/status/{job_id}   Poll progress (0-100%)
```

### Facebook Authentication

3 Login Methods:
| Method | Endpoint | How |
|--------|----------|-----|
| Browser window | `POST /auth/fb-login` | Opens visible Chrome, user logs in manually |
| Cookie paste | `POST /auth/set-cookies` | Paste `document.cookie` from browser console |
| Chrome profile | `GET /auth/fb-cookies-from-profile` | Reads existing logged-in Chrome profile |

All methods persist cookies to SQLite — survive server restarts.

### Profile Scraper

Scrape public profiles from multiple platforms:
| Platform | Method |
|----------|--------|
| Instagram | API (no browser) |
| Twitter / X | API (no browser) |
| Facebook | Selenium |
| Reddit | Selenium |
| GitHub | Selenium |
| TikTok | Selenium |
| Pinterest | Selenium |

**Endpoint:** `POST /scrape/profile`

### Media Proxy

**Stream Proxy:** `GET /proxy/media?url=...`
- Streams Facebook CDN media through server (CORS bypass)
- Auto-detects content type

**Download with DASH Merge:** `GET /proxy-download?url=...&audio_url=...`
- Downloads video directly to client
- Merges video + audio using `ffmpeg` for DASH reels

### Data Storage (SQLite)

All scrape sessions and posts stored in `scraper.db`:
- Tables: `scrape_sessions`, `posts`, `app_settings`
- Posts tagged by `content_type`: `post` or `reel`
- Full-text search on caption
- Paginated with `limit` / `offset`

**Endpoints:**
```
GET    /db/sessions              List all sessions
GET    /db/sessions/{id}         One session + posts
DELETE /db/sessions/{id}
GET    /db/posts                 Paginated with filters
DELETE /db/posts/{id}
GET    /db/stats                 Totals
GET    /db/export/excel          Download .xlsx
```

### Excel Export

Export posts or reels to `.xlsx`:
- Columns: #, Image (embedded, 160×160px), Caption, Date, Post URL
- Images fetched + resized + padded via Pillow
- Hyperlinked post URLs
- Frozen header row, auto-filter
- Supports `post_ids` param for selected-post export

---

## 6. Multi-Tenant Admin

### API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/admin/login` | JWT login (admin/admin) |
| `GET` | `/api/v1/tenants` | List all tenants |
| `POST` | `/api/v1/tenants` | Create tenant (generates API key) |
| `GET` | `/api/v1/tenants/{id}` | Tenant details |
| `PUT` | `/api/v1/tenants/{id}` | Update tenant config |
| `DELETE` | `/api/v1/tenants/{id}` | Delete tenant + all data |

### Per-Tenant Configuration

Each tenant has independent:
- **LLM Provider + Model + API Key** — Different LLMs per tenant
- **Embedding Provider** — hash/fastembed/openai/gemini/mistral
- **Retrieval Settings** — top_k, weights, reranker type
- **Chunking Settings** — max tokens, overlap, semantic
- **Session Settings** — memory limit, retention days
- **Rate Limits** — requests per minute
- **System Prompt** — custom instruction prepended to queries

### API Keys

- Generated on tenant creation: `rbs_rag_sk_{32_hex_chars}`
- Fernet-encrypted at rest (when `RAG_ENCRYPTION_KEY` is set)
- Used in `X-API-Key` header for client endpoints

### Isolation Audit

`GET /api/v1/isolation-check` verifies:
- No chunks leak between tenants
- Each tenant's SQLite only contains their data
- Score: 100% = fully isolated

---

## 7. Cloud Sync

| Provider | Status | Description |
|---|---|---|
| Google Drive | ✅ | Sync files from shared Drive links |
| OneDrive | ✅ | Microsoft OneDrive integration |
| Amazon S3 | ✅ | AWS S3 bucket sync |
| Confluence | ✅ | Confluence page export |

### API

```bash
POST /api/v1/tenants/{id}/cloud-sync
{
  "provider": "google_drive",
  "cloud_url_or_id": "https://drive.google.com/...",
  "auto_ingest": true
}
```

Files are downloaded to tenant documents directory, then optionally auto-ingested.

---

## 8. Monitoring & Security

### Metrics (Prometheus)

| Metric | Type | Description |
|---|---|---|
| `documents_ingested_total` | Counter | Documents processed |
| `chunks_created_total` | Counter | Chunks created |
| `chunks_retrieved` | Histogram | Chunks per query |
| `llm_requests_total` | Counter | LLM API calls |
| `llm_duration_seconds` | Histogram | LLM response time |
| `prompt_injections_blocked_total` | Counter | Blocked attacks |
| `active_tenants` | Gauge | Current tenant count |

**Endpoint:** `GET /metrics`

### Prompt Injection Detection

Two-layer detection:
1. **Regex patterns** — SQL injection, prompt leaking, role-play attacks
2. **ML model** (DeBERTa) — Optional, for higher accuracy

When detected:
- Blocked pattern → Returns rejection message
- Suspicious → Returns answer with `confidence: "low"`

### Audit Logs

All admin operations logged to `admin_store.activity_log`:
- Ingestion runs (success/error, doc/chunk counts)
- Tenant CRUD operations
- Failed login attempts
- Rate limit violations (optional)

### Rate Limiting (Redis-backed)

| Endpoint | Limit | Window |
|---|---|---|
| Admin chat | 60 RPM | 60s sliding window |
| Admin stream | 30 RPM | 60s sliding window |
| Client chat | 60 RPM | 60s sliding window |
| Client stream | 30 RPM | 60s sliding window |

Redis uses **Sorted Set** with timestamps as scores. Old entries purged on each check.

### Security Features

- API keys encrypted at rest (Fernet symmetric encryption)
- JWT tokens for admin sessions
- CORS middleware (configurable origins)
- File upload validation (extension + size)
- SSRF protection (blocked private IPs, metadata endpoints)
- HTTPS via nginx (optional SSL)

---

## 9. OCR Service

### Engines

| Engine | Type | Description |
|---|---|---|
| **PaddleOCR** | Local | Open-source, good for printed text. Pre-configured |
| **Mistral OCR** | Cloud API | High accuracy, supports handwriting |
| **Nemotron** | NVIDIA NIM | GPU-accelerated, enterprise-grade |

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/ocr/image` | OCR single image |
| `POST` | `/ocr/pdf` | OCR PDF (all pages) |
| `POST` | `/ocr/batch` | Batch OCR multiple files |
| `GET` | `/health` | Engine availability |
| `GET` | `/benchmark` | Performance test |

### Advanced OCR Features

#### Searchable PDF Export
```
POST /ocr/export/searchable-pdf
```
Run OCR and return a searchable PDF with an invisible text layer. Allows full-text search on scanned documents.

#### Excel Export
```
POST /ocr/export/excel
```
Run OCR and export regions as an Excel workbook with:
- Summary sheet (file info, processing time, word count)
- Per-page region sheets (text, confidence, bounding boxes)
- Full text sheets

#### Image Preprocessing Pipeline
```
POST /ocr/preprocess
```
Apply configurable preprocessing steps:
- Grayscale conversion
- Noise reduction
- Contrast enhancement
- Adaptive thresholding
- Auto-rotation/deskew
- Dynamic upscaling for low-DPI images

#### Barcode / QR Detection
```
POST /ocr/barcode
```
Detect barcodes and QR codes in images using pyzbar or OpenCV fallback.

#### Document Classification
```
POST /ocr/classify
```
Classify document type using OCR text + keyword heuristics:
- Invoice, Receipt, Resume, Passport, ID Card
- Bank Statement, Medical, Newspaper, Research, Form

#### Layout Visualization
```
POST /ocr/visualize
```
Return annotated image with OCR bounding boxes drawn. Color-coded by confidence (green > 80%, yellow > 50%, red < 50%).

#### Background Job Queue
```
POST /ocr/jobs/submit       Submit large file for background OCR
GET  /ocr/jobs/{job_id}     Get job status
GET  /ocr/jobs              List recent jobs
```
Asynchronous OCR processing for large files with progress tracking.

#### Monitoring & Metrics
```
GET /ocr/metrics
```
Service-level metrics: total requests, success rate, average processing time, words extracted, errors.

### Hybrid PDF Pipeline

For PDFs processed via PaddleOCR:
- Extracts **native text** from digital PDF pages directly
- Detects **scanned pages** (low character count) and renders to images
- Applies **OCR** only where needed
- Configurable threshold: `MIN_TEXT_CHARS_THRESHOLD`

### Image Preprocessing

Applied automatically before PaddleOCR inference:
- Grayscale conversion and adaptive binarization
- Noise reduction and contrast enhancement
- Dynamic upscaling for low-DPI images
- Orientation correction support

### Rich Structured Output

Every response includes:
- `full_text` — plain text of entire document
- `markdown` — formatted Markdown (Mistral only)
- `tables` — extracted tables in HTML format
- `hyperlinks` — extracted URLs
- `paragraphs` / `lines` / `words` — split text at different granularities
- `regions` — bounding boxes + confidence scores per text region
- `entities` — auto-extracted URLs, emails, phone numbers
- `processing_time_ms` — per-request timing

---

## 10. CLI Tool

```bash
# Initialize config
python -m rbs_rag init

# Ingest documents from directory
python -m rbs_rag ingest

# Search without LLM
python -m rbs_rag search "your query"

# Ask with LLM
python -m rbs_rag ask "your question"

# Interactive chat
python -m rbs_rag chat
```

The CLI uses the same `RagEngine` as the web server, but operates directly on the filesystem without HTTP.

---

## 11. Redis Feature Summary

| Feature | Redis Data Structure | Key Pattern | TTL | Graceful Fallback |
|---|---|---|---|---|
| Rate Limiting | Sorted Set (ZSET) | `rate_limit:{ip}` | 60s | Allow all requests |
| Ingestion Status | Hash/String (JSON) | `ingestion:{tenant_id}` | 3600s | In-memory dict |
| Scraper Cache | String (JSON) | `scraper_cache:{url}` | 300s | Cache miss → re-fetch |
| Job Store | String (JSON) | `scraper_job:{job_id}` | 86400s | In-memory store |
| LLM Response Cache | String (JSON) | `llm_cache:{hash}` | 3600s | Cache miss → call LLM |
| Crawl Queue | List | `scraper_queue` | — | In-memory queue |
