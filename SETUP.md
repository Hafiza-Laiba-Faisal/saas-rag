# TenBit RAG Platform — Setup Guide

## Project Structure

```
RAG/
├── chic-interface-design/   # Frontend (React/Vite SPA)
├── rbs-rag-node/            # Backend (Node.js/TypeScript API)
├── scraper-service/         # Scraper microservice (Docker)
├── ocr-service-main/        # OCR microservice (Docker)
├── docker-compose.yml       # All Docker services
└── dev-start.sh / dev-start.ps1  # One-command dev launcher
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | 18+ | https://nodejs.org |
| Docker Desktop | Latest | https://docker.com |
| Git | Any | https://git-scm.com |

---

## First-Time Setup

### 1. Clone & configure environment

```bash
git clone <repo-url>
cd RAG
cp .env.example .env
# Edit .env and set your API keys if needed
```

### 2. Install dependencies

```bash
# Backend
cd rbs-rag-node
npm install
npm run prisma:generate
npm run prisma:migrate
cd ..

# Frontend
cd chic-interface-design
npm install
cd ..
```

### 3. Start Docker services (3 containers required)

```bash
docker compose up -d qdrant redis scraper_service ocr_service
```

> **What each container does:**
> - **`qdrant`** — Vector database (port 6333)
> - **`redis`** — Cache layer (port 6379)
> - **`scraper_service`** — Web scraper microservice (port 8002)
> - **`ocr_service`** — OCR microservice for image/scanned PDFs (port 8000)

### 4. Start development servers

**Terminal 1 — Frontend:**
```bash
cd chic-interface-design
npm run dev
```
→ Opens at http://localhost:3000

**Terminal 2 — Backend:**
```bash
cd rbs-rag-node
SCRAPER_SERVICE_URL=http://localhost:8002 npm run dev
```
→ API at http://localhost:3001

---

## One-Command Dev Start

Instead of running everything manually, use the dev-start script:

**Linux / macOS:**
```bash
chmod +x dev-start.sh
./dev-start.sh
```

**Windows (PowerShell — run as Administrator):**
```powershell
.\dev-start.ps1
```

The script will:
1. Start all 3 Docker containers
2. Wait for them to be healthy
3. Start the backend dev server
4. Start the frontend dev server
5. Open the browser automatically

---

## Environment Variables (`.env`)

Key variables for local dev (in `rbs-rag-node/.env` or root `.env`):

| Variable | Default | Description |
|---|---|---|
| `SCRAPER_SERVICE_URL` | `http://localhost:8002` | Scraper microservice URL |
| `RAG_ADMIN_PASSWORD` | `admin` | Admin dashboard password |
| `RAG_QDRANT_HOST` | `localhost` | Qdrant host (use `localhost` for local dev) |
| `RAG_QDRANT_PORT` | `6333` | Qdrant port |
| `RAG_REDIS_HOST` | `localhost` | Redis host (use `localhost` for local dev) |
| `RAG_LLM_PROVIDER` | `gemini` | LLM provider (`gemini`, `openai`, `anthropic`) |
| `RAG_LLM_API_KEY` | *(empty)* | Global LLM API key (optional) |

> **Note:** When running locally (not in Docker), set `RAG_QDRANT_HOST=localhost` and `RAG_REDIS_HOST=localhost`. The `.env.example` uses `qdrant`/`redis` as hostnames which only work inside Docker networking.

---

## Ports Reference

| Service | Port | URL |
|---|---|---|
| Frontend | **5173** | http://localhost:5173 |
| Backend API | 3001 | http://localhost:3001 |
| Qdrant | 6333 | http://localhost:6333 |
| Redis | 6379 | (internal) |
| Scraper | 8002 | http://localhost:8002 |
| OCR | 8000 | http://localhost:8000 |

---

## Cloud Sync — Supported Providers

The Cloud Sync feature supports publicly shared files:

| Provider | What works |
|---|---|
| **Google Drive** | Files shared as "Anyone with the link" |
| **OneDrive** | Files shared as "Anyone with the link" |
| **S3** | Public bucket URLs or presigned URLs |
| **Confluence** | Public pages, or private pages with API token |

---

## Stopping Everything

**Linux:**
```bash
# Stop Docker containers
docker compose stop qdrant redis scraper_service

# Stop dev servers: Ctrl+C in each terminal
```

**Windows:**
```powershell
docker compose stop qdrant redis scraper_service
# Stop dev servers: Ctrl+C in each terminal (or close the windows)
```
