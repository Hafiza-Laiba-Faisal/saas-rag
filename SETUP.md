# Setup Guide — TenBit RAG Platform

This guide covers a clean Docker deployment (recommended), the keys/authentication you must configure, and the manual/development setup. If you're a fresh contributor who just `git clone`d the repo, start with the **Quick Start (Docker)** below.

---

## 1. Prerequisites

| Dependency | Version | Purpose |
|---|---|---|
| Git | any | Cloning the repo |
| Docker Engine | 24+ | Container runtime |
| Docker Compose v2 | latest | Orchestrates `qdrant`, `redis`, `rag_api`, `ocr_service`, `scraper_service`, `nginx` |
| curl | any | Verifying health endpoints |
| Python | >= 3.11 | Only for **manual** (non-Docker) dev backend |
| Node.js | >= 22 | Only for **manual** frontend dev |

> Docker is required. All five backend services are containerised. Do **not** install Python/Node packages unless you plan to run the stack without Docker.

---

## 2. Quick Start (Docker)

### 2.1 Clone & configure

```bash
git clone <repo-url>
cd RAG

# Create your environment file
cp .env.example .env
```

### 2.2 Generate the required secrets

Create or edit `.env` before the first start. Do not paste shell substitutions like `$(...)` directly into `.env`; generate the values first and then copy the final strings into the file.

```bash
# Example values for .env — replace with your own secrets
# ── REQUIRED ────────────────────────────────────────────────────────────
# Fernet key that encrypts tenants' stored API keys at rest.
RAG_ENCRYPTION_KEY=<paste-generated-fernet-key-here>

# ── Admin dashboard authentication ──────────────────────────────────────
# Setting RAG_ADMIN_JWT_SECRET enables login protection on the admin UI.
# Leave it empty to keep the admin open (not recommended for production).
RAG_ADMIN_JWT_SECRET=<paste-random-secret-here>
RAG_ADMIN_PASSWORD=change-me-strong-password
RAG_ADMIN_AUTH_ENABLED=true

# ── Global LLM key (optional; multi-tenant setups leave this empty and give
#    each tenant its own key when creating it) ───────────────────────────
RAG_LLM_PROVIDER=gemini
RAG_LLM_MODEL=gemini-2.5-flash-lite
RAG_LLM_API_KEY=

# ── LLM rate-limit protection (optional) ─────────────────────────────────
# Minimum seconds between outbound LLM requests (per host). Prevents HTTP 429
# from rate-limited providers (e.g. Mistral free tier = 1 req/s) during batch
# LLM calls. 0 disables throttling; fast paid providers are never throttled
# by default.
RAG_LLM_MIN_INTERVAL=1.5
```

Generate the secret values locally:

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY

python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
```

> **Important:** `RAG_LLM_API_KEY` is **not required** to start the platform. In a multi-tenant deployment each tenant supplies its own LLM/embedding keys through the admin dashboard. The minimum values needed to boot are the encryption key and the admin auth values.

### 2.3 Build & run

```bash
docker compose up --build -d
```

> Verified on this repository: the stack comes up with `qdrant`, `redis`, `rag_api`, `ocr_service`, `scraper_service`, and `nginx` using the Docker workflow above.

### 2.4 Verify the stack

If you run the scraper service in Docker and see `Permission denied` while crawling, make sure the container has a writable crawl-output path. The compose file already mounts the host folder and exports these variables for the scraper service:

```bash
SCRAPER_OUTPUT_ROOT=/app/crawl_output
SCRAPER_OUTPUT_FALLBACK=/app/crawl_output
```

```bash
docker compose ps
# All 6 services should be Up (healthy); if OCR/scraper are still "starting"
# give them 60–120s (first boot initialises model/browser assets — see §6).

# Backend health (through nginx → rag_api).
# nginx terminates TLS with a self-signed cert and redirects :80 → :443,
# so use https and -k (or your own cert):
curl -k https://localhost/api/v1/health
# {"status":"ok","db":"connected","qdrant":"connected", ...}

# OCR + scraper (proxied by nginx)
curl -k https://localhost/health     # scraper/ocr health
curl -k https://localhost/version
```

> nginx listens on `:80` (redirects to `:443`) and `:443` (TLS). It ships with a **self-signed** cert in `nginx/ssl/` — browsers will warn; accept it locally or replace `nginx/ssl/cert.pem`/`key.pem` with real ones. Use `curl -k` throughout these examples.

Ports after startup (all reachable through nginx on `:80` / `:443` by default; override with `HTTP_PORT`/`HTTPS_PORT` in `.env`):

| Service | Container | Direct port | Notes |
|---|---|---|---|
| nginx | `tenbit-nginx` | `80, 443` | The only port you should expose to clients |
| rag_api | `tenbit-rag-api` | — (65535 internal) | serves `/api/v1/*` + the admin SPA |
| ocr_service | `tenbit-ocr` | `8000` (published) | `POST /ocr*` |
| scraper_service | `tenbit-scraper` | `8002` (published) | `POST /crawl/*`, `/scrape/*` |
| qdrant | `tenbit-qdrant` | `6333, 6334` | vector DB |
| redis | `tenbit-redis` | `6379` | caching/jobs |

### 2.5 Open the dashboard

```bash
open https://localhost
```

- If you set `RAG_ADMIN_JWT_SECRET`, you'll be asked to **Log in** (username `admin`, password `RAG_ADMIN_PASSWORD`).
- If you left it empty, the dashboard opens without a login.
- Browsers warn about the self-signed cert on first load — click through / trust it.

---

## 3. First Boot — what is generated

On `rag_api` start, `docker/docker-entrypoint.sh`:

1. Reads `.env`
2. Creates `/data/.rbs_rag/{config.json, tenants/}`
3. Writes `config.json` from your environment variables
4. Starts `uvicorn` (default `UVICORN_WORKERS=4`)

`config.json` is regenerated on **every** container start — you don't format it by hand, just edit `.env` and `docker compose restart rag_api`.

### Creating an admin session (JWT)

If `RAG_ADMIN_JWT_SECRET` is set, admin endpoints require a bearer token:

```bash
curl -k -X POST https://localhost/api/v1/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_RAG_ADMIN_PASSWORD"}'
# → { "status":"success","token":"<JWT>", ... }

# Use it for admin calls:
curl -k https://localhost/api/v1/tenants -H "Authorization: Bearer <JWT>"
```

### Creating a tenant

```bash
curl -k -X POST https://localhost/api/v1/tenants \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "name": "Demo Corp",
    "llm_provider": "gemini",
    "llm_model": "gemini-2.5-flash-lite",
    "llm_api_key": "your-tenant-gemini-key"
  }'

# Response contains the tenant's client api_key. Use it as X-API-Key below.
```

### Consuming the tenant API (client)

Client-facing endpoints authenticate with `X-API-Key` (not the admin JWT):

```bash
API_KEY=<tenant api_key>

# Upload
curl -k -X POST https://localhost/api/v1/tenants/demo/documents \
  -H "X-API-Key: $API_KEY" -F "files=@./sample.pdf"

# Ingest
curl -k -X POST https://localhost/api/v1/tenants/demo/ingest -H "X-API-Key: $API_KEY"

# Chat
curl -k -X POST https://localhost/api/v1/tenants/demo/chat \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"What does this document say?"}'
```

---

## 4. Daily operations (Docker)

```bash
# Start everything
docker compose up -d

# Stop everything
docker compose down

# Logs (follow one service)
docker compose logs -f rag_api
docker compose logs -f ocr_service
docker compose logs -f scraper_service

# Restart a single service
docker compose restart scraper_service

# Rebuild a single service after local code changes
docker compose build ocr_service && docker compose up -d ocr_service
```

Prefer `docker compose` over raw `docker start/stop tenbit-*` — it manages the shared network, volumes and health order.

---

## 5. Manual Setup (Development, without Docker)

You still need Redis + Qdrant running (use Docker for just those two):

```bash
# 1. Python virtualenv + dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[all]"

# 2. Redis + Qdrant only via Docker
docker run -d --name rag-redis  -p 6379:6379 redis:7-alpine redis-server --appendonly yes
docker run -d --name rag-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest

# 3. Environment file
cp .env.example .env   # then edit — see §2.2 for required keys

# 4. Start backend (port 3001)
RAG_ROOT_DIR='.rbs_rag' \
QDRANT_HOST=localhost QDRANT_PORT=6333 \
RAG_REDIS_HOST=localhost REDIS_HOST=localhost REDIS_PORT=6379 \
REDIS_ENABLED=true \
SCRAPER_SERVICE_URL=http://localhost:8002 \
PYTHONPATH=src \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/uvicorn rbs_rag.web.server:app --host 127.0.0.1 --port 3001 --reload

# 5. Frontend dev (separate terminal)
cd chic-interface-design && npm install && npm run dev   # → http://localhost:5173
```

> **`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`** — set these to avoid HuggingFace network calls on startup. The reranker uses a local word-overlap algorithm with no model downloads required.

### Dev launcher (all-in-one)

```bash
./dev-start.sh
# Opens separate terminal windows for backend, frontend, and docker logs.
# Requires konsole / gnome-terminal / xterm.
```

### Environment Variables (reference)

| Variable | Default | Description |
|---|---|---|
| `RAG_ENCRYPTION_KEY` | — | **Required.** Fernet key encrypting stored API keys |
| `RAG_ADMIN_JWT_SECRET` | — | Enables admin auth + `/login` (empty = admin open) |
| `RAG_ADMIN_PASSWORD` | `admin` | Admin login password |
| `RAG_ADMIN_AUTH_ENABLED` | `false` | Enables admin auth guard |
| `RAG_LLM_API_KEY` / `PROVIDER` / `MODEL` | — / `gemini` / `gemini-2.5-flash-lite` | Global LLM fallback (optional) |
| `RAG_LLM_MIN_INTERVAL` | `1.5` | Min seconds between outbound LLM requests (per host) — prevents HTTP 429 from rate-limited providers (e.g. Mistral free tier, 1 req/s). `0` disables throttling. Fast paid providers (OpenAI/Anthropic) are never throttled by default |
| `RAG_EMBEDDING_PROVIDER` | `hash` | `hash`, `bge`, `bge_m3`, `openai`, `gemini` |
| `RAG_QDRANT_HOST` / `PORT` | `qdrant` / `6333` | Vector DB |
| `RAG_REDIS_HOST` / `PORT` / `PASSWORD` | `redis` / `6379` / — | Cache + jobs |
| `RAG_SPA_DIR` | `./chic-interface-design/dist-spa` | Built admin/client SPA |
| `SCRAPER_SERVICE_URL` | `http://scraper_service:8000` | RAG → scraper microservice |
| `DEEPCRAWL_API_KEY` | — | Scraper fallback for blocked sites |
| `MISTRAL_API_KEY` / `NEMOTRON_API_KEY` | — | OCR engines (local PaddleOCR still works without them) |
| `OCR_LANGUAGES` | `en,ur,ar` | OCR languages |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Public nginx ports (compose) |

---

## 6. OCR & Scraper: no more startup "infinite loop"

Fresh installs sometimes saw `tenbit-ocr` / `tenbit-scraper` appear to loop on boot. Causes & fixes built into this repo:

1. **Multiple uvicorn workers** — both services hold process-local state (PaddleOCR/onnxruntime models; scraper crawl jobs, rate-limit and cookies). With `--workers 2` each worker re-initialised models in parallel and the scraper's in-memory `job_id` couldn't be shared across workers (polls returned 404). Both Dockerfiles now run **`--workers 1`**. To scale, run additional containers, not workers.

2. **Health check teardown on first boot** — first boot downloads models/binaries (OCR) and Chromium (scraper) which can exceed a short `start-period`. Both Dockerfiles now use `start-period=60s --retries=5` so they aren't torn down mid-start.

If a service still reports not-healthy:

```bash
docker compose ps                # Status column: Up (healthy) / Up (starting)
docker compose logs -f ocr_service    # read the actual error, don't rely on /health
docker compose logs -f scraper_service

# OCR can boot with zero remote engines (PaddleOCR local). MISTRAL/NEMOTRON_API_KEY
# are optional. If PaddleOCR fails to download models, set:
#   export OCR_LANGUAGES=en  and  export PADDLEOCR_HOME=/app/models
```

---

## 7. Troubleshooting

| Symptom | Check / fix |
|---|---|
| Service won't start / needs Redis | `docker compose ps redis`; backend falls back to in-memory without crash |
| Frontend blank/404 on `/` | SPA not built into image → rebuild `docker compose build rag_api`; or `cd chic-interface-design && npm run build:spa` |
| Qdrant errors | `curl http://qdrant:6333/health` inside stack, or host: `curl :6333/health` |
| Encrypted-key mismatch (old data) | You changed `RAG_ENCRYPTION_KEY` → delete re-created tables: `docker compose exec rag_api rm -rf /data/.rbs_rag` (⚠️ deletes all tenants/docs) |
| OCR/scraper stuck at "starting" longer than 2 min | Read logs; on the first boot only, models/Chromium may download (needs internet). Afterwards they start fast. |
| 404 on scrape job poll | Ensure `scraper_service` runs with 1 worker (see §6) so the in-memory job store matches |
| Backend hangs on first query (dev) | Set `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` — prevents HuggingFace network retries |

---

## 8. Key-local reminders for fresh contributors

- Don't commit `.env` (it holds secrets). `.env` is git-ignored.
- Never commit a real API key. When you see `RAG_ENCRYPTION_KEY=...` or a JWT secret in a PR/diff, rotate it.
- If you were given a staging/storybook the project is connected to Lovable: **do not rebase/force-push/amend pushed history**.
- Run `docker compose down` before deleting the repo, and `docker compose down -v` only if you also want to wipe volumes.