# TenBit RAG Platform

> **Enterprise-Grade Multi-Tenant RAG Platform with Integrated OCR & Web Scraping**

A production-ready Retrieval-Augmented Generation platform built for enterprise deployments. Features multi-tenant isolation, hierarchical chunking, hybrid search, and integrates with best-in-class OCR and web scraping microservices.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TENBIT RAG PLATFORM                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   RAG Core      │  │   OCR Service   │  │  Scraper Service│             │
│  │   (Port 8100)   │  │   (Port 8001)   │  │  (Port 8002)    │             │
│  │                 │  │                 │  │                 │             │
│  │ • Multi-tenant  │  │ • Mistral OCR   │  │ • Recursive     │             │
│  │   RAG Engine    │  │ • PaddleOCR     │  │   Crawl         │             │
│  │ • Hybrid Search │  │ • Hybrid PDF    │  │ • Facebook      │             │
│  │ • Session/User  │  │ • Batch API     │  │   Scraper       │             │
│  │   Memory        │  │ • Tables/MD     │  │ • Media Proxy   │             │
│  │ • SSE Streaming │  │ • Entities      │  │ • Profile       │             │
│  │ • Admin Dashboard│  │ • Rate Limited │  │   Scraper       │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                      │
│           └────────────────────┼────────────────────┘                      │
│                                │                                          │
│                    ┌───────────▼───────────┐                              │
│                    │   React Dashboard     │                              │
│                    │   (Single Page App)   │                              │
│                    └───────────┬───────────┘                              │
│                                │                                          │
│                    ┌───────────▼───────────┐                              │
│                    │   Data Layer          │                              │
│                    │   • SQLite (Admin +   │                              │
│                    │     Per-Tenant DB)    │                              │
│                    │   • Qdrant (Vector)   │                              │
│                    │   • Redis (Cache)     │                              │
│                    └───────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Docker)

### Prerequisites

- **Docker Engine** 24+ with Compose V2
- **Git** (to clone the repo)
- **4+ GB RAM** allocated to Docker

### 1. Clone & Configure

```bash
git clone <repo-url> /projects/TenBit/RAG
cd /projects/TenBit/RAG

# Edit .env — set your LLM API key (Gemini, OpenAI, or Anthropic)
#   RAG_LLM_API_KEY=your-api-key-here
```

### 2. Launch Everything

```bash
docker compose up -d
```

Wait ~30 seconds for health checks. Verify:

```bash
curl http://localhost/api/v1/health
# {"status":"ok","db":"connected","qdrant":"connected",...}
```

### 3. Access

| Service | URL |
|---------|-----|
| **Admin Dashboard** | http://localhost |
| **Widget Demo** | http://localhost/widget |
| **API (via Nginx)** | http://localhost/api/v1/chat |
| **Qdrant Dashboard** | http://localhost:6333/dashboard |

### 4. Create Your First Tenant

```bash
curl -X POST http://localhost/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"demo","name":"Demo Client","llm_api_key":"'$RAG_LLM_API_KEY'"}'
```

### 5. (Optional) Start OCR / Scraper Microservices

```bash
docker compose --profile all up -d
```

---

## 📦 Project Structure

```
/projects/TenBit/RAG/
├── Dockerfile                  # Multi-stage build for rag_api
├── docker-compose.yml          # Orchestrates all services
├── .env                        # Single config point (git-ignored)
├── .env.example                # Template with all variables
├── .dockerignore               # Build context exclusions
├── nginx/
│   └── nginx.conf              # Reverse proxy config
│   └── ssl/                    # HTTPS certs (create if needed)
├── docker/
│   └── docker-entrypoint.sh    # Auto-generates config.json on start
├── IMPROVEMENTS_ANALYSIS.md
├── FEATURES.md
├── README.md
├── SETUP.md
├── ARCHITECTURE.md
├── database_analysis.md
├── improvements.md
├── pyproject.toml
├── rag.docx
├── run-rag.ps1
├── src/
│   └── rbs_rag/
│       ├── __init__.py
│       ├── __main__.py         # CLI entry point
│       ├── chunking.py         # Hierarchical + semantic chunking
│       ├── cli.py              # CLI commands
│       ├── cloud_sync.py       # Google Drive/OneDrive sync
│       ├── config.py           # Configuration management
│       ├── document_loaders.py # Document parsing + OCR integration
│       ├── embeddings.py       # Embedding providers
│       ├── engine.py           # Core RAG engine
│       ├── llm.py              # LLM providers (Gemini, OpenAI, Anthropic)
│       ├── models.py           # Pydantic models
│       ├── reranking.py        # Reranking (heuristic + BGE planned)
│       ├── retrieval.py        # Hybrid search + retrieval
│       ├── store.py            # SQLite storage
│       ├── text.py             # Text processing utilities
│       ├── validation.py       # Self-RAG validation
│       ├── vector_store.py     # Qdrant abstraction (planned)
│       └── web/
│           ├── __init__.py
│           ├── admin_db.py     # Multi-tenant admin database
│           ├── server.py       # FastAPI server + endpoints
│           ├── static/
│           │   ├── index.html  # React dashboard (SPA)
│           │   └── widget.html # Embeddable chat widget
│           └── web_run.py      # Web server entry point
├── ocr-service-main/           # OCR Microservice
│   ├── main.py                 # FastAPI entry point
│   ├── api/routers/ocr.py      # OCR endpoints
│   ├── ocr/engines/            # Mistral + PaddleOCR engines
│   ├── pdf/                    # Hybrid PDF pipeline
│   ├── preprocessing/          # Image preprocessing
│   ├── postprocessing/         # Table parsing, Japanese correction
│   ├── services/               # Business logic services
│   ├── schemas/                # Pydantic schemas
│   ├── config/settings.py      # Configuration
│   ├── FEATURES.md
│   ├── ARCHITECTURE.md
│   ├── SETUP.md
│   └── README.md
└── scraper-service-main/       # Scraper Microservice
    ├── app/
    │   ├── main.py             # FastAPI entry point
    │   ├── api/routes/         # All API endpoints
    │   ├── core/               # Core pipeline (fetch, parse, extract)
    │   ├── scrapers/           # Platform-specific scrapers
    │   ├── storage/            # SQLite storage
    │   ├── session/            # Browser session management
    │   ├── jobs/               # Background job processing
    │   └── schemas/            # Pydantic schemas
    ├── FEATURES.md
    ├── ARCHITECTURE.md
    ├── SETUP.md
    ├── README.md
    └── requirements.txt
```

---

## 🔧 Configuration

### RAG Core (`.rbs_rag/config.json`)

```json
{
  "llm": {
    "provider": "gemini",
    "api_key": "${RAG_LLM_API_KEY}",
    "model": "gemini-2.5-flash-lite",
    "base_url": "https://generativelanguage.googleapis.com/v1beta",
    "fallback_models": ["gemini-2.5-flash"]
  },
  "embeddings": {
    "provider": "hash",
    "dimensions": 384,
    "model": "BAAI/bge-small-en-v1.5",
    "api_key": "${RAG_LLM_API_KEY}"
  },
  "retrieval": {
    "top_k": 20,
    "rerank_top_k": 8,
    "final_context_k": 5,
    "dense_weight": 0.55,
    "sparse_weight": 0.45
  },
  "chunking": {
    "max_tokens": 320,
    "overlap_tokens": 48
  }
}
```

### OCR Service (`.env`)

```env
MISTRAL_API_KEY=your_mistral_key_here
MAX_FILE_SIZE_MB=50
OCR_LANGUAGES=en,ur,ar
USE_GPU=false
PAGE_RENDER_DPI=150
MIN_TEXT_CHARS_THRESHOLD=20
MIN_IMAGE_DPI=150
LOG_LEVEL=INFO
OCR_API_KEY=optional_api_key_for_auth
```

### Scraper Service (`.env`)

```env
DEEPCRAWL_API_KEY=your_deepcrawl_key_for_cloudflare_bypass
MAX_CONNECTIONS=100
MAX_KEEPALIVE_CONNECTIONS=20
APP_TITLE="Scraper Service"
APP_VERSION="1.0.0"
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[IMPROVEMENTS_ANALYSIS.md](IMPROVEMENTS_ANALYSIS.md)** | Comprehensive architecture gap analysis with 156-hour implementation plan |
| **[FEATURES.md](FEATURES.md)** | Complete feature documentation with production target state |
| **[SETUP.md](SETUP.md)** | Detailed installation and configuration guide |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System design with diagrams and data flows |
| **[API.md](API.md)** | Complete API reference for all three services |
| **[database_analysis.md](database_analysis.md)** | Vector database comparison and migration strategy |
| **[improvements.md](improvements.md)** | Prioritized improvement tracking |

---

## 🛠️ Development

### Run Tests

```bash
export PYTHONPATH="src"
python -m unittest discover -s tests -v
```

### CLI Usage

```bash
# Initialize
rag init

# Ingest documents
rag ingest ./docs --kb default

# Search
rag search "query" --kb default

# Chat
rag chat --kb default --session my-session

# User memory
rag memory set role "support manager" --user alice
```

### Code Quality

```bash
# Format
black src/
isort src/

# Lint
ruff check src/
mypy src/
```

---

## 🚢 Production Deployment

### Docker Compose (Implemented)

The project ships with a complete `docker-compose.yml` covering all core services:

| Service | Container | Image | Purpose |
|---------|-----------|-------|---------|
| **rag_api** | tenbit-rag-api | Build from `./Dockerfile` | RAG engine + admin dashboard |
| **nginx** | tenbit-nginx | `nginx:alpine` | Reverse proxy (ports 80/443) |
| **qdrant** | tenbit-qdrant | `qdrant/qdrant:latest` | Vector database |
| **redis** | tenbit-redis | `redis:7-alpine` | Caching + rate limiting |
| **ocr_service** | tenbit-ocr | Build from `./ocr-service-main/Dockerfile` | OCR microservice (profile: all) |
| **scraper_service** | tenbit-scraper | Build from `./scraper-service-main/Dockerfile` | Web scraper microservice (profile: all) |

### Deploy to Production

```bash
# 1. Copy project to server, then:
# 2. Set your LLM API key
nano .env

# 3. Start all services
docker compose up -d

# 4. (Optional) Add SSL — place certs in nginx/ssl/, update nginx.conf
#     then restart: docker compose restart nginx
```

### Client Integration

Clients connect using the **X-API-Key** header. Each tenant gets a unique key:

```bash
curl -X POST "https://yourdomain.com/api/v1/chat" \
  -H "X-API-Key: rbs_rag_sk_<tenant_secret>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the policy?", "session_id": "session-123"}'
```

Or embed the floating chat widget on any website:

```html
<script>
(function() {
var iframe = document.createElement('iframe');
iframe.src = "https://yourdomain.com/widget?api_key=rbs_rag_sk_<tenant_secret>";
iframe.style = "position: fixed; bottom: 20px; right: 20px; width: 380px; height: 600px; border: none; z-index: 999999; border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.5);";
document.body.appendChild(iframe);
})();
</script>
```

### Environment Variables

All config lives in a single `.env` file at the project root. Key variables:

```env
# Required — set your LLM provider key
RAG_LLM_API_KEY=your-gemini-or-openai-api-key

# Optional — defaults are suitable for most deployments
RAG_LLM_PROVIDER=gemini
RAG_LLM_MODEL=gemini-2.5-flash-lite
RAG_EMBEDDING_PROVIDER=hash
RAG_QDRANT_HOST=qdrant
RAG_REDIS_HOST=redis
RAG_LOG_LEVEL=INFO
```

---

## 📊 Current Status vs Production Target

| Component | Current | Target | Status |
|-----------|---------|--------|--------|
| Vector DB | SQLite (O(n)) | Qdrant (HNSW) | 🔴 Migration needed |
| Embeddings | sentence-transformers (BGE) | BGE-M3 | 🟡 Local models available |
| Reranker | Heuristic | BGE Cross-Encoder | 🟡 Partial (sentence-transformers installed) |
| Chunking | Hierarchical | Hierarchical + Semantic | 🟡 Partial |
| Streaming | Sync + SSE | SSE | 🟢 Implemented |
| OCR | Fallback integration | Auto-fallback | 🟢 Integrated |
| Scraping | URL ingestion + crawl | Recursive crawl | 🟢 Integrated |
| Auth | API Key only | JWT + OAuth | 🟡 Basic |
| Observability | Basic logging | Prometheus + Tracing | 🔴 Minimal |
| Duplicate Detection | SQLite document_id check | Full dedup pipeline | 🟢 Implemented |
| Document UI | 3-panel tabs (Upload/Ingested/Scraped) | Refined UX | 🟢 Implemented |

See **[IMPROVEMENTS_ANALYSIS.md](IMPROVEMENTS_ANALYSIS.md)** for detailed 7-phase, 156-hour implementation plan.

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

---

## 📄 License

MIT License - see LICENSE file for details.

---

## 🆘 Support

- **Issues**: GitHub Issues
- **API Docs**: `/docs` endpoint when running (http://localhost/api/v1/docs)
- **Architecture Spec**: `rag.docx`

---

**Built for Enterprise** • Multi-Tenant • Production-Ready • Extensible
