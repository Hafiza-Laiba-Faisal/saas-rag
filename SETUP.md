# Setup Guide — TenBit RAG Platform

## Prerequisites

| Dependency | Version | Purpose |
|---|---|---|
| Python | >= 3.11 | Backend runtime |
| Node.js | >= 22 | Frontend build |
| Docker & Docker Compose | Latest | Containerised deployment |
| Redis | 7.x (in Docker) | Distributed caching, rate limiting, job queue |
| Qdrant | Latest (in Docker) | Vector database |

---

## Quick Start (Docker)

```bash
# 1. Clone & branch
git clone <repo-url>
cd RAG
git checkout production-ready-system

# 2. Environment
cp .env.example .env
# Edit .env — at minimum set LLM_API_KEY

# 3. Build & run
docker compose up --build -d

# 4. Verify
curl http://localhost/api/v1/health
# Expected: {"status":"ok","db":"connected","qdrant":"connected","uptime_seconds":...}

# 5. Open dashboard
open http://localhost
```

---

## Daily Workflow (After First Install)

```bash
# 1. Start all Docker containers (Redis, Qdrant, nginx, RAG API, OCR, scraper)
docker start tenbit-redis tenbit-qdrant tenbit-nginx tenbit-rag-api tenbit-ocr tenbit-scraper

# Stop all containers
docker stop tenbit-redis tenbit-qdrant tenbit-nginx tenbit-rag-api tenbit-ocr tenbit-scraper

# Or via docker compose
# docker compose up -d            # start
# docker compose down             # stop + remove containers

# 2. Start Python backend (port 3001)
cd /home/tenbitsolutions/Documents/Tenbit/3-ongoing-projects/RAG
RAG_ENCRYPTION_KEY="B-172W0V3jwK2duLwFPFkwJLGSpz2C62uR-D-HKJF7w=" \
PYTHONPATH=src \
  .venv/bin/uvicorn rbs_rag.web.server:app --host 0.0.0.0 --port 3001

# 3. Start frontend dev server (separate terminal)
cd /home/tenbitsolutions/Documents/Tenbit/3-ongoing-projects/RAG/chic-interface-design
npm run dev
# → http://localhost:5173

# 4. Or use built SPA (no frontend server needed)
# Just open http://localhost:3001 after backend starts
```

## Manual Setup (Development)

### 1. Python Backend

```bash
cd RAG

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -e ".[all]"
# Or minimal: pip install -e ".[qdrant]" redis

# Environment
cp .env.example .env
# Edit .env with your keys — at minimum set RAG_ENCRYPTION_KEY
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Redis (Required for cache/rate-limiting)

```bash
docker run -d --name tenbit-redis \
  -p 6379:6379 \
  redis:7-alpine \
  redis-server --appendonly yes
```

### 3. Qdrant (Required for vector search)

```bash
docker run -d --name tenbit-qdrant \
  -p 6333:6333 -p 6334:6334 \
  qdrant/qdrant:latest
```

### 4. Run Backend (Development Server)

```bash
# Ensure env vars are set (or edit .env)
export RAG_ENCRYPTION_KEY="your-encryption-key"
export PYTHONPATH=src:$PYTHONPATH

# Start dev server (hot reload)
cd src
source ../.venv/bin/activate
uvicorn rbs_rag.web.server:app --reload --host 0.0.0.0 --port 3001

# Or using .venv directly from project root:
# PYTHONPATH=src .venv/bin/uvicorn rbs_rag.web.server:app --reload --host 0.0.0.0 --port 3001
```

> **Note:** The first time you start with a new/changed `RAG_ENCRYPTION_KEY`, delete any existing `admin.db`:
> ```bash
> rm -f .rbs_rag/admin.db src/.rbs_rag/admin.db
> ```
> The database will be recreated fresh on next startup.

### 5. Frontend (SPA Build)

```bash
cd chic-interface-design

# Install dependencies
npm install

# Build SPA (output: dist-spa/)
npm run build:spa

# Backend auto-serves from dist-spa/ — no extra config needed
```

### 6. Frontend (Dev Mode with Hot Reload)

```bash
cd chic-interface-design

# Start Vite dev server (proxy /api → http://127.0.0.1:3001)
npm run dev
# → http://localhost:5173

# The Vite proxy forwards /api/* requests to the Python backend on :3001
# Make sure the backend is running first (step 4)
```

### 7. Verify Full Stack

```bash
# Backend health
curl http://localhost:3001/api/v1/health

# Frontend (built SPA served by backend)
open http://localhost:3001

# Or in dev mode
open http://localhost:5173
```

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `RAG_LLM_API_KEY` | — | Gemini / OpenAI / Anthropic API key |
| `RAG_LLM_PROVIDER` | `gemini` | LLM provider |
| `RAG_LLM_MODEL` | `gemini-2.5-flash-lite` | Model name |
| `RAG_ROOT_DIR` | `.rbs_rag` | Data directory for SQLite + documents |

### Qdrant

| Variable | Default | Description |
|---|---|---|
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant REST port |

### Redis

| Variable | Default | Description |
|---|---|---|
| `RAG_REDIS_HOST` | `redis` | Redis host |
| `RAG_REDIS_PORT` | `6379` | Redis port |
| `RAG_REDIS_PASSWORD` | — | Redis password (optional) |

### Frontend

| Variable | Default | Description |
|---|---|---|
| `RAG_SPA_DIR` | `./chic-interface-design/dist-spa` | Path to built SPA |

### Admin

| Variable | Default | Description |
|---|---|---|
| `RAG_ADMIN_JWT_SECRET` | — | JWT signing key (set for auth) |
| `RAG_ADMIN_PASSWORD` | `admin` | Admin login password |
| `RAG_ENCRYPTION_KEY` | — | Fernet key for API key encryption |

### Scraper Service

| Variable | Default | Description |
|---|---|---|
| `REDIS_ENABLED` | `false` | Enable Redis-backed cache & job store |
| `REDIS_HOST` | `redis` | Redis host for scraper |
| `REDIS_PORT` | `6379` | Redis port for scraper |
| `DEEPCRAWL_API_KEY` | — | DeepCrawl API key |

---

## Docker Compose Services

| Service | Container | Ports | Depends On |
|---|---|---|---|
| `rag_api` | `tenbit-rag-api` | — (via nginx) | qdrant, redis |
| `ocr_service` | `tenbit-ocr` | 8000 | — |
| `scraper_service` | `tenbit-scraper` | 8002 | — |
| `qdrant` | `tenbit-qdrant` | 6333, 6334 | — |
| `redis` | `tenbit-redis` | 6379 | — |
| `nginx` | `tenbit-nginx` | 80, 443 | rag_api, ocr_service, scraper_service |

```bash
# View logs
docker compose logs -f rag_api

# Restart single service
docker compose restart rag_api

# Rebuild
docker compose build rag_api
```

---

## First-Time Setup

### Create Admin Account

```bash
# No admin auth by default. Set RAG_ADMIN_JWT_SECRET in .env to enable.
# Default admin login: admin / admin
```

### Create a Tenant

```bash
curl -X POST http://localhost:3001/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "name": "Demo Corp",
    "llm_provider": "gemini",
    "llm_model": "gemini-2.5-flash-lite",
    "llm_api_key": "your-gemini-api-key"
  }'

# Response includes api_key for client access
```

### Upload & Ingest

```bash
# Upload a document
curl -X POST http://localhost:3001/api/v1/tenants/demo/documents \
  -F "files=@./sample.pdf"

# Start ingestion
curl -X POST http://localhost:3001/api/v1/tenants/demo/ingest

# Check status
curl http://localhost:3001/api/v1/tenants/demo/ingest/status
```

### Chat with Your Data

```bash
curl -X POST http://localhost:3001/api/v1/tenants/demo/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this document say?"}'
```

---

## Troubleshooting

### Redis not connecting

```bash
# Check Redis is running
docker compose ps redis

# Test connection
docker compose exec redis redis-cli ping
# Should return: PONG

# Backend fallback: no Redis = in-memory mode (no crash, just no persistence)
```

### Frontend not loading

```bash
# Ensure SPA is built
ls -la chic-interface-design/dist-spa/index.html

# Check backend SPA path
curl http://localhost:3001/ | head -5
# Should return HTML (React root), not "Frontend not built yet"
```

### Qdrant connection issues

```bash
# Check Qdrant health
curl http://localhost:6333/health

# Backend fallback: Qdrant unavailable = degraded search (SQLite fallback)
```
