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

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for frontend development)
- **Git**

### 1. Clone and Setup RAG Core

```bash
cd /projects/TenBit/RAG

# Install Python dependencies
python -m pip install -e .

# Or with local ML extras for embeddings + Qdrant
python -m pip install -e ".[local-ml]"

# Start Qdrant vector database (Docker required)
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest

# Initialize configuration
rag init
```

### 2. Start OCR Service (Terminal 1)

```bash
cd /projects/TenBit/RAG/ocr-service-main

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env: Add MISTRAL_API_KEY for cloud OCR (optional - has local fallback)

# Start service on port 8001
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Start Scraper Service (Terminal 2)

```bash
cd /projects/TenBit/RAG/scraper-service-main

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Configure environment (optional)
cp .env.example .env
# Edit .env: Add DEEPCRAWL_API_KEY for Cloudflare bypass

# Start service on port 8002
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### 4. Start RAG API + Dashboard (Terminal 3)

```bash
cd /projects/TenBit/RAG

# Set Python path
export PYTHONPATH="src"  # Windows: $env:PYTHONPATH="src"

# Start web server on port 8100
python -m rbs_rag.web_run
```

### 5. Access the Dashboard

Open **http://localhost:8100** in your browser.

- **Admin Dashboard**: Full multi-tenant management
- **Chat Interface**: RAG-powered Q&A with citations
- **Document Management**: Upload, OCR status, ingestion
- **URL Ingestion**: Submit URLs for scraping
- **System Logs**: Audit trail and activity

---

## 📦 Project Structure

```
/projects/TenBit/RAG/
├── IMPROVEMENTS_ANALYSIS.md    # Comprehensive architecture analysis
├── FEATURES.md                 # Complete feature documentation
├── README.md                   # This file
├── SETUP.md                    # Detailed installation guide
├── ARCHITECTURE.md             # System design documentation
├── API.md                      # Complete API reference
├── database_analysis.md        # Vector DB comparison
├── improvements.md             # Improvement tracking
├── pyproject.toml              # Python package config
├── rag.docx                    # Original architecture spec
├── run-rag.ps1                 # Windows run script
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

### Docker Compose (Planned)

```yaml
services:
  rag-api:
    build: .
    ports: ["8100:8100"]
    environment:
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
    depends_on: [qdrant, redis, postgres]

  ocr-service:
    build: ./ocr-service-main
    ports: ["8001:8000"]
    environment:
      - MISTRAL_API_KEY=${MISTRAL_API_KEY}

  scraper-service:
    build: ./scraper-service-main
    ports: ["8002:8000"]
    environment:
      - DEEPCRAWL_API_KEY=${DEEPCRAWL_API_KEY}

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: [qdrant_data:/qdrant/storage]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=tenbit_rag
      - POSTGRES_USER=tenbit
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]

volumes:
  qdrant_data:
  postgres_data:
```

### Environment Variables for Production

```env
# RAG Core
RAG_LLM_API_KEY=your_llm_key
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379
DATABASE_URL=postgresql://tenbit:pass@postgres/tenbit_rag
ADMIN_JWT_SECRET=your_jwt_secret
CORS_ORIGINS=https://yourdomain.com

# OCR Service
MISTRAL_API_KEY=your_mistral_key
OCR_API_KEY=your_ocr_api_key

# Scraper Service
DEEPCRAWL_API_KEY=your_deepcrawl_key
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
- **Documentation**: `/docs` endpoint when running (http://localhost:8100/docs)
- **Architecture Spec**: `rag.docx` and `.rbs_rag/tenants/testing-gdrive/documents/rag.md`

---

**Built for Enterprise** • Multi-Tenant • Production-Ready • Extensible
