# TenBit RAG — Complete Setup Guide

This guide covers the full stack:
- **Node.js RAG API** (`rbs-rag-node`) — main backend
- **OCR Service** (`ocr-service-main`) — Python, runs as Docker container
- **Qdrant** — vector database, runs as Docker container
- **Redis** — caching, runs as Docker container
- **Frontend** (`chic-interface-design`) — React/Vite SPA

---

## Prerequisites

| Tool | Min Version | Install |
|------|-------------|---------|
| Node.js | 22.x | https://nodejs.org |
| npm | 10.x | bundled with Node |
| Docker | 24.x | https://docs.docker.com/get-docker/ |
| Docker Compose | v2 (plugin) | bundled with Docker Desktop |
| Git | any | https://git-scm.com |

Check versions:
```bash
node -v
npm -v
docker -v
docker compose version
```

---

## 1. Clone the Repository

```bash
git clone https://github.com/Hafiza-Laiba-Faisal/saas-rag.git
cd saas-rag
git checkout nodejs-port
```

---

## 2. Environment Files

### 2a. Node API — `rbs-rag-node/.env`

```bash
cp rbs-rag-node/.env.example rbs-rag-node/.env
```

Open `rbs-rag-node/.env` and fill in:

```env
# Database (SQLite, no setup needed)
DATABASE_URL=file:./dev.db

# LLM — pick one provider and add its key
LLM_PROVIDER=gemini                        # gemini | openai | anthropic
LLM_API_KEY=your-api-key-here
LLM_MODEL=gemini-2.5-flash-lite

# Embeddings (hash = no external API needed, good for dev)
EMBEDDING_PROVIDER=hash
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384

# Qdrant — matches the Docker container below
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=

# Redis — matches the Docker container below
REDIS_HOST=localhost
REDIS_PORT=6379

# Admin dashboard
ADMIN_PASSWORD=admin
ADMIN_JWT_SECRET=change-me-use-a-long-random-string

# Server
PORT=3001
LOG_LEVEL=info

# OCR Service — points to the Python Docker container
OCR_SERVICE_URL=http://localhost:8000
OCR_API_KEY=                               # leave empty if not set in OCR service
```

### 2b. OCR Service — `ocr-service-main/.env`

```bash
cp ocr-service-main/.env.example ocr-service-main/.env
```

Fill in (all optional — only needed for vision-based OCR engines):

```env
MISTRAL_API_KEY=          # for Mistral Vision OCR engine
NEMOTRON_API_KEY=         # for Nemotron Vision OCR engine
OCR_LANGUAGES=en          # comma-separated: en,ar,ur etc.
```

> PaddleOCR engine works offline — no API key needed.

---

## 3. Start Docker Containers (Qdrant + Redis + OCR)

These are the Python/infrastructure services that Node depends on.

```bash
cd rbs-rag-node
docker compose -f docker-compose.node.yml up -d
```

Then start the OCR service separately (it's not in `docker-compose.node.yml` yet):

```bash
cd ../ocr-service-main
docker build -t tenbit-ocr .
docker run -d \
  --name tenbit-ocr \
  -p 8000:8000 \
  --env-file .env \
  tenbit-ocr
```

Verify all containers are up:

```bash
docker ps
```

Expected output:
```
CONTAINER ID   IMAGE                  PORTS                    NAMES
xxxxxxxxxxxx   tenbit-ocr             0.0.0.0:8000->8000/tcp   tenbit-ocr
xxxxxxxxxxxx   rbs-rag-node-qdrant    0.0.0.0:6333->6333/tcp   rbs-rag-node-qdrant-1
xxxxxxxxxxxx   redis:7-alpine         0.0.0.0:6379->6379/tcp   rbs-rag-node-redis-1
```

Health checks:

```bash
# Qdrant
curl http://localhost:6333/healthz

# OCR Service
curl http://localhost:8000/health

# Redis
docker exec rbs-rag-node-redis-1 redis-cli ping
# Expected: PONG
```

---

## 4. Node.js API Setup

```bash
cd rbs-rag-node
npm install
```

Initialize the database (creates SQLite file + runs Prisma migrations):

```bash
npx prisma generate
npx prisma migrate dev --name init
```

Start in dev mode (hot reload):

```bash
npm run dev
```

Or build and start in production mode:

```bash
npm run build
npm start
```

API will be running at: **http://localhost:3001**

Verify:
```bash
curl http://localhost:3001/health
```

---

## 5. Frontend Setup

```bash
cd chic-interface-design
npm install
```

Start dev server:

```bash
npm run dev
```

Frontend will be at: **http://localhost:5173**

> The frontend talks to the Node API at `http://localhost:3001` by default.
> If you change the API port, update `src/lib/api.ts`.

Build for production (outputs to `dist-spa/`):

```bash
npm run build
```

---

## 6. Full Stack — All at Once

Open 3 terminals:

**Terminal 1 — Docker services:**
```bash
cd rbs-rag-node && docker compose -f docker-compose.node.yml up
```

**Terminal 2 — Node API:**
```bash
cd rbs-rag-node && npm run dev
```

**Terminal 3 — Frontend:**
```bash
cd chic-interface-design && npm run dev
```

---

## 7. Service URLs Summary

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:5173 | React SPA |
| Node API | http://localhost:3001 | REST API |
| OCR Service | http://localhost:8000 | Python/FastAPI |
| Qdrant Dashboard | http://localhost:6333/dashboard | Vector DB UI |
| Redis | localhost:6379 | No UI by default |

---

## 8. Common Issues

**`ECONNREFUSED` on Qdrant**
Qdrant container is not running. Run `docker compose -f docker-compose.node.yml up -d` from `rbs-rag-node/`.

**Prisma migration error on first run**
Run `npx prisma migrate dev --name init` from `rbs-rag-node/`. This creates `prisma/dev.db`.

**OCR service returns 500**
Check container logs: `docker logs tenbit-ocr`. Usually a missing API key or the model is still downloading on first boot (PaddleOCR downloads ~200MB on first run).

**Frontend 404 on API calls**
Make sure the Node API is running on port `3001`. Check `src/lib/api.ts` for the base URL.

**`npm install` fails on `chic-interface-design`**
This project uses Vite 8 which requires Node 22. Run `node -v` to confirm.

---

## 9. Stopping Everything

```bash
# Stop Docker containers
cd rbs-rag-node && docker compose -f docker-compose.node.yml down

# Stop OCR container
docker stop tenbit-ocr && docker rm tenbit-ocr
```

To remove all data volumes (full reset):
```bash
cd rbs-rag-node && docker compose -f docker-compose.node.yml down -v
```
