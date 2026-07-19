# RBS RAG Node.js — Setup Guide

## Prerequisites

- **Node.js** 22+ (includes npm)
- **Docker** (for Qdrant vector database)
- **TypeScript** (installed via npm)
- Git (to clone)

---

## Quick Start (Development)

### 1. Install Dependencies

```bash
cd rbs-rag-node
cp .env.example .env
# Edit .env — at minimum set LLM_API_KEY and ADMIN_JWT_SECRET
npm install
```

### 2. Setup Database

```bash
npm run setup
# Runs: prisma generate + prisma migrate dev --name init
```

### 3. Start Qdrant (Docker)

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

### 4. Seed Demo Tenant (Optional)

```bash
npm run seed
# Creates a demo tenant with API key rbs_rag_sk_<hex>
```

### 5. Start Server

```bash
npm run dev
# Uses tsx watch — auto-restarts on file changes
```

Server runs at **http://localhost:3001**

---

## One-Command Dev Start

```bash
./scripts/start-dev.sh
```

This script:
1. Kills any existing server + Qdrant container
2. Starts Qdrant via Docker
3. Runs Prisma setup + seed
4. Builds TypeScript
5. Starts server in background
6. Writes logs to `.logs/server.log`

View logs:
```bash
tail -f .logs/server.log
```

Stop:
```bash
./scripts/stop-dev.sh
```

---

## Manual Setup Steps

### Environment Variables (`.env`)

```bash
# --- Database ---
DATABASE_URL=file:./dev.db

# --- LLM ---
LLM_PROVIDER=gemini
LLM_API_KEY=your-gemini-api-key
LLM_MODEL=gemini-2.5-flash-lite

# --- Embeddings ---
EMBEDDING_PROVIDER=hash
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384

# --- Qdrant ---
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=

# --- Redis (optional) ---
REDIS_HOST=localhost
REDIS_PORT=6379

# --- Admin ---
ADMIN_PASSWORD=admin
ADMIN_JWT_SECRET=change-me-in-production-use-a-long-random-string

# --- Server ---
PORT=3001
LOG_LEVEL=info

# --- OCR Service ---
OCR_SERVICE_URL=http://localhost:8000
```

### Available npm Scripts

| Command | Purpose |
|---|---|
| `npm run setup` | Prisma generate + migrate (one-time) |
| `npm run build` | `tsc` compile to `dist/` |
| `npm start` | `node dist/index.js` (production) |
| `npm run dev` | `tsx watch src/index.ts` (dev with auto-restart) |
| `npm run seed` | `tsx src/seed.ts` — creates demo tenant |
| `npm run lint` | `tsc --noEmit` (type-check only) |

---

## Docker Deployment

### docker-compose.node.yml

The project includes a Docker Compose setup with two services:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  rag-node:
    build: .
    ports:
      - "3001:3001"
    depends_on:
      - qdrant
    env_file:
      - .env
    environment:
      QDRANT_HOST: qdrant
      QDRANT_PORT: 6333
    volumes:
      - ./tenants:/app/tenants
      - ./static:/app/static
      - ./prisma:/app/prisma
      - rag_data:/app/.rbs_rag
    restart: unless-stopped
```

### Build & Run

```bash
# Build
docker compose -f docker-compose.node.yml build

# Start
docker compose -f docker-compose.node.yml up -d

# View logs
docker compose -f docker-compose.node.yml logs -f

# Stop
docker compose -f docker-compose.node.yml down

# Full clean (destroys volumes)
docker compose -f docker-compose.node.yml down -v
```

### Dockerfile

Multi-stage build:
- **Stage 1 (builder)**: `node:22-slim`, installs deps, generates Prisma client, compiles TypeScript
- **Stage 2 (runtime)**: `node:22-slim`, copies only production deps + compiled JS

```bash
# Build manually
docker build -t rbs-rag-node .
docker run -d --name rag-node -p 3001:3001 --env-file .env rbs-rag-node
```

---

## Configuration Reference

### Core Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | `file:./dev.db` | SQLite database path |
| `PORT` | No | `3001` | Server port |
| `LOG_LEVEL` | No | `info` | Logging level |

### LLM Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | No | `gemini` | `gemini`, `openai`, `openai_compatible`, `anthropic`, `mistral` |
| `LLM_API_KEY` | Yes* | — | LLM API key (*required if no per-tenant keys) |
| `LLM_MODEL` | No | `gemini-2.5-flash-lite` | Model name |
| `LLM_BASE_URL` | No | — | Custom API base URL (for Ollama, etc.) |
| `LLM_FALLBACK_MODELS` | No | — | Comma-separated fallback models |

### Embedding Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | No | `hash` | `hash`, `openai`, `gemini` |
| `EMBEDDING_MODEL` | No | `BAAI/bge-small-en-v1.5` | Model name |
| `EMBEDDING_DIMENSIONS` | No | `384` | Vector dimensions |
| `EMBEDDING_API_KEY` | No | — | API key for cloud embeddings |

### Retrieval Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `RETRIEVAL_TOP_K` | No | `20` | Initial candidate count |
| `RETRIEVAL_RERANK_TOP_K` | No | `8` | Candidates sent to reranker |
| `RETRIEVAL_FINAL_CONTEXT_K` | No | `5` | Final context window size |
| `RETRIEVAL_DENSE_WEIGHT` | No | `0.55` | Dense rank weight in RRF |
| `RETRIEVAL_SPARSE_WEIGHT` | No | `0.45` | Sparse rank weight in RRF |
| `RERANKER_TYPE` | No | `local` | Reranker type |

### Chunking Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `CHUNKING_MAX_TOKENS` | No | `320` | Max tokens per chunk |
| `CHUNKING_OVERLAP_TOKENS` | No | `48` | Token overlap between windows |
| `CHUNKING_SEMANTIC` | No | `false` | Enable semantic chunk merging |

### Qdrant Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `QDRANT_HOST` | No | `localhost` | Qdrant hostname |
| `QDRANT_PORT` | No | `6333` | Qdrant gRPC/HTTP port |
| `QDRANT_API_KEY` | No | — | Qdrant API key |
| `QDRANT_HTTPS` | No | `false` | Enable HTTPS for Qdrant |

### Security Config

| Variable | Required | Default | Description |
|---|---|---|---|
| `ADMIN_PASSWORD` | No | `admin` | Admin dashboard password |
| `ADMIN_JWT_SECRET` | **Yes** | — | JWT signing secret (32+ chars) |
| `CORS_ORIGINS` | No | `*` | CORS allowed origins |
| `RATE_LIMIT_ENABLED` | No | `true` | Enable rate limiting |
| `RATE_LIMIT_RPM` | No | `60` | Requests per minute per IP |

---

## API Reference

All endpoints are under `/api/v1`. Server runs at `http://localhost:3001`.

### Admin Auth

**POST /api/v1/admin/login**
```json
{ "username": "admin", "password": "<ADMIN_PASSWORD>" }
```
Response: `{ "status": "success", "token": "eyJ...", "token_type": "Bearer" }`

Use token as `Authorization: Bearer <token>` for admin endpoints.

### Tenant Management

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/tenants` | List all tenants |
| POST | `/api/v1/tenants` | Create tenant |
| GET | `/api/v1/tenants/:id` | Get tenant details |
| PUT | `/api/v1/tenants/:id` | Update tenant |
| DELETE | `/api/v1/tenants/:id` | Delete tenant (cascade) |

**POST /api/v1/tenants**
```json
{
  "tenant_id": "acme-corp",
  "name": "Acme Corporation",
  "llm_provider": "gemini",
  "llm_model": "gemini-2.5-flash-lite",
  "llm_api_key": "your-api-key"
}
```
Response: `{ "status": "success", "tenantId": "acme-corp", "apiKey": "rbs_rag_sk_<hex>" }`

### Documents

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/tenants/:id/documents` | List documents |
| POST | `/api/v1/tenants/:id/documents` | Upload documents (multipart) |
| GET | `/api/v1/tenants/:id/documents/:filename` | View/download document |
| DELETE | `/api/v1/tenants/:id/documents/:filename` | Delete document (with Qdrant cleanup) |
| GET | `/api/v1/tenants/:id/documents/:filename/chunks` | Get document chunks |

### Ingestion

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/tenants/:id/ingest` | Start ingestion |
| GET | `/api/v1/tenants/:id/ingest/status` | Get ingestion status |

Optional query param: `?apply_ocr=true` to route through OCR service.

### Chat

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/tenants/:id/chat` | Sync chat |
| POST | `/api/v1/tenants/:id/chat/stream` | SSE streaming chat |
| POST | `/api/v1/chat` | Client chat (X-API-Key) |
| POST | `/api/v1/chat/stream` | Client streaming (X-API-Key) |

**Chat Body:**
```json
{
  "query": "What is the refund policy?",
  "session_id": "session-123",
  "user_id": "web-user",
  "system_prompt": null,
  "filters": null
}
```

### Scrape

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/tenants/:id/scrape` | Scrape URL (admin) |
| POST | `/api/v1/client/scrape` | Scrape URL (client) |

**Scrape Body:**
```json
{
  "url": "https://example.com",
  "crawl": false,
  "full_site": false,
  "max_pages": 10,
  "max_depth": 2
}
```

### Sessions

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/tenants/:id/sessions` | List sessions |
| GET | `/api/v1/tenants/:id/sessions/:sid/turns` | Get session turns |
| DELETE | `/api/v1/tenants/:id/sessions/:sid` | Delete session |
| POST | `/api/v1/tenants/:id/sessions/purge` | Purge expired sessions |

### System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/system/status` | System overview |
| GET | `/api/v1/system/logs` | Activity logs |
| GET | `/api/v1/isolation-check` | Multi-tenant isolation audit |
| POST | `/api/v1/terminal/exec` | Terminal commands |
| POST | `/api/v1/tenants/:id/cloud-sync` | Cloud sync |

### Client Chat via API Key

```bash
curl -X POST http://localhost:3001/api/v1/chat \
  -H "X-API-Key: rbs_rag_sk_<tenant_secret>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the policy?", "session_id": "session-123"}'
```

---

## Project Structure

```
rbs-rag-node/
├── .env                     # Environment variables
├── .env.example             # Template
├── package.json
├── tsconfig.json
├── Dockerfile
├── docker-compose.node.yml
├── prisma/
│   └── schema.prisma        # 5 models: Tenant, Document, Chunk, SessionTurn, ActivityLog
├── src/
│   ├── index.ts             # Express app entry
│   ├── config.ts            # Env-driven + per-tenant config
│   ├── engine.ts            # RagEngine orchestrator
│   ├── store.ts             # DbStore (Prisma)
│   ├── adminStore.ts        # AdminStore (tenant CRUD)
│   ├── vectorStore.ts       # QdrantVectorStore
│   ├── embeddings.ts        # Embedding providers
│   ├── chunking.ts          # HierarchicalChunker
│   ├── llm.ts               # LLMClient (Gemini/OpenAI/Anthropic)
│   ├── retrieval.ts         # HybridRetriever
│   ├── reranking.ts         # LocalReranker
│   ├── validation.ts        # Retrieval validation
│   ├── documentLoaders.ts   # File loaders
│   ├── scraper.ts           # Web scraper
│   ├── ocrClient.ts         # OCR HTTP client
│   ├── providerPresets.ts   # Provider preset CRUD
│   ├── text.ts              # BM25, cosine sim, tokenize
│   ├── seed.ts              # Demo tenant seeder
│   └── types/models.ts      # All interfaces
├── routes/
│   └── index.ts             # All Express routes
├── static/                  # Static frontend files
├── dist/                    # Compiled JS output
└── .logs/                   # Dev server logs
```

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `PrismaClientInitializationError` | DATABASE_URL not set | Ensure `.env` has `DATABASE_URL=file:./dev.db` |
| Qdrant search returns empty | Qdrant not running | `docker start qdrant` or `docker run -d --name qdrant -p 6333:6333 qdrant/qdrant` |
| `401 Unauthorized` | Invalid/missing JWT | Login at `POST /api/v1/admin/login` |
| `ERR_MODULE_NOT_FOUND` | Missing `.js` extension in import | TypeScript ESM requires `.js` in imports |
| Scraper returns "No text extracted" | JS-rendered site | Use crawler with Playwright (separate service) |
| API key not found | Wrong prefix | Keys start with `rbs_rag_sk_` |

```bash
# View all logs (Docker)
docker compose -f docker-compose.node.yml logs -f

# Restart after config changes
docker compose -f docker-compose.node.yml down && docker compose -f docker-compose.node.yml up -d

# Reset database
rm dev.db && npm run setup && npm run seed
```
