# TenBit RAG — Setup Guide

## Prerequisites

- Linux/macOS (Windows via WSL2)
- Bash, curl, OpenSSL
- 4+ GB RAM for Docker
- Git (to clone)

The `start.sh` script installs Docker, Python 3.11+, and OpenSSL automatically if missing.

## Quick Start (One Command)

```bash
git clone <repo-url> /projects/TenBit/RAG
cd /projects/TenBit/RAG
sudo ./start.sh
```

`start.sh` does the full bootstrap:
1. Checks OS and package manager
2. Installs Python 3.11+ if missing
3. Installs Docker + Docker Compose if missing
4. Creates `.env` from `.env.example` or `.env.docker` if not present
5. Generates self-signed SSL certificates to `nginx/ssl/server.{key,crt}` (nginx expects `cert.pem`/`key.pem` — copy or symlink)
6. Installs Python dependencies locally (for CLI tools)
7. Pulls base images and builds containers
8. Starts all services via `docker compose up -d`
9. Runs health check (hits `/health` endpoint)

After boot, open **https://localhost/**, accept the self-signed cert warning, and login with `admin` / `admin`.

## Manual Setup (Without start.sh)

### 1. Environment File

```bash
cp .env.example .env
```

### 2. Generate Encryption Key (Required)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the output to `.env`:
```
RAG_ENCRYPTION_KEY=<generated-key>
```

### 3. SSL Certificates

```bash
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout nginx/ssl/server.key -out nginx/ssl/server.crt \
  -subj "/C=PK/ST=Islamabad/L=Islamabad/O=TenBit/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"
cp nginx/ssl/server.crt nginx/ssl/cert.pem
cp nginx/ssl/server.key nginx/ssl/key.pem
```

### 4. Build and Start

```bash
docker compose build
docker compose up -d
```

### 5. Verify

```bash
curl -sk https://localhost/api/v1/health
```

## Configuration (.env)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RAG_LLM_API_KEY` | No | -- | Global LLM fallback (leave empty for per-tenant keys) |
| `RAG_LLM_PROVIDER` | No | `gemini` | `gemini`, `openai_compatible`, or `anthropic` |
| `RAG_LLM_MODEL` | No | `gemini-2.5-flash-lite` | Model name |
| `RAG_EMBEDDING_PROVIDER` | No | `hash` | Embedding provider |
| `RAG_ENCRYPTION_KEY` | **Yes** | -- | Fernet key (44-char base64) for API key encryption |
| `RAG_ADMIN_JWT_SECRET` | **Yes** | -- | JWT secret for admin auth (32+ chars) |
| `RAG_ADMIN_PASSWORD` | No | `admin` | Admin dashboard login password |
| `RAG_TERMINAL_ENABLED` | No | `true` | Enable terminal endpoint |
| `RAG_CORS_ORIGINS` | No | `["*"]` | CORS origins |
| `QDRANT_HOST` | No | `qdrant` | Qdrant hostname |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `RAG_REDIS_PASSWORD` | No | -- | Redis password |
| `MISTRAL_API_KEY` | No | -- | Mistral cloud OCR (optional) |
| `NEMOTRON_API_KEY` | No | -- | NVIDIA Nemotron OCR (requires NIM container) |
| `DEEPCRAWL_API_KEY` | No | -- | DeepCrawl API key for Cloudflare bypass |
| `UVICORN_WORKERS` | No | `4` | Number of uvicorn workers |

## API Reference

All endpoints are proxied through nginx at `https://localhost/`.

### Admin Auth

**POST /api/v1/admin/login**

```json
{"username": "admin", "password": "<RAG_ADMIN_PASSWORD>"}
```

Response: `{"status": "success", "token": "eyJ...", "token_type": "Bearer"}`

Use the token as `Authorization: Bearer <token>` for admin endpoints.

### Tenant Management (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/tenants` | List all tenants |
| POST | `/api/v1/tenants` | Create tenant |
| GET | `/api/v1/tenants/{id}` | Get tenant details |
| PUT | `/api/v1/tenants/{id}` | Update tenant |
| DELETE | `/api/v1/tenants/{id}` | Delete tenant |

**POST /api/v1/tenants** body:

```json
{
  "tenant_id": "acme-corp",
  "name": "Acme Corporation",
  "llm_provider": "gemini",
  "llm_model": "gemini-2.5-flash-lite",
  "llm_api_key": "your-api-key",
  "llm_base_url": null,
  "embedding_provider": "hash",
  "system_prompt": null
}
```

Response: `{"status": "success", "tenant_id": "acme-corp", "api_key": "rbs_rag_sk_<hex>"}`

### Tenant Documents (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/tenants/{id}/documents` | List documents |
| POST | `/api/v1/tenants/{id}/documents` | Upload documents (multipart) |
| GET | `/api/v1/tenants/{id}/documents/{filename}` | View/download document |
| DELETE | `/api/v1/tenants/{id}/documents/{filename}` | Delete document |
| GET | `/api/v1/tenants/{id}/documents/{filename}/chunks` | Get document chunks |

### Tenant Ingest (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tenants/{id}/ingest` | Trigger ingestion pipeline |
| GET | `/api/v1/tenants/{id}/ingest/status` | Get ingestion status |

### Tenant Chat (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tenants/{id}/chat` | Chat with tenant's KB |
| POST | `/api/v1/tenants/{id}/chat/stream` | SSE streaming chat |

Chat body:

```json
{
  "query": "What is the policy?",
  "session_id": "session-123",
  "user_id": "web-user",
  "system_prompt": "You are a helpful assistant. Answer based on the provided documents."
}
```

The `system_prompt` field is optional. If omitted, the tenant's configured system prompt is used. Both the admin playground sidebar and client dashboard provide a system prompt editor.

### Tenant Scrape (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tenants/{id}/scrape` | Scrape a URL |
| GET | `/api/v1/tenants/{id}/scrape/jobs` | List scrape jobs |
| GET | `/api/v1/tenants/{id}/scrape/jobs/{job_id}` | Get job details |

### Tenant Sessions (Admin, JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/tenants/{id}/sessions` | List chat sessions |
| GET | `/api/v1/tenants/{id}/sessions/{sid}/turns` | Get session turns |
| DELETE | `/api/v1/tenants/{id}/sessions/{sid}` | Delete session |
| POST | `/api/v1/tenants/{id}/sessions/purge` | Purge expired sessions |

### Other Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/system/status` | System overview (tenants, docs, chunks) |
| GET | `/api/v1/system/logs` | Activity logs |
| GET | `/api/v1/system/ocr-status` | OCR engine availability |
| GET | `/api/v1/isolation-check` | Multi-tenant isolation audit |
| POST | `/api/v1/terminal/exec` | Execute terminal commands |
| POST | `/api/v1/tenants/{id}/cloud-sync` | Sync cloud documents |
| POST | `/api/v1/tenants/{id}/ocr` | OCR a document |
| GET | `/metrics` | Prometheus metrics |

### Client Endpoints (X-API-Key header or `?api_key=` query param)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat` | Chat with KB |
| POST | `/api/v1/chat/stream` | SSE streaming chat |
| GET | `/api/v1/client/documents` | List documents |
| POST | `/api/v1/client/documents` | Upload documents |
| GET | `/api/v1/client/documents/{filename}` | View/download document |
| DELETE | `/api/v1/client/documents/{filename}` | Delete document |
| POST | `/api/v1/client/ingest` | Trigger ingestion |
| GET | `/api/v1/client/ingest/status` | Ingestion status |
| POST | `/api/v1/client/scrape` | Scrape a URL |

### Chat via API Key

```bash
curl -X POST https://localhost/api/v1/chat \
  -H "X-API-Key: rbs_rag_sk_<tenant_secret>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the policy?", "session_id": "session-123"}'
```

### Widget Embed

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

### System Prompt Override

Both admin playground and client dashboard have a sidebar/panel to view and edit the system prompt. The system prompt is stored per-tenant in the admin DB. It can also be overridden per chat request by passing `"system_prompt": "..."` in the chat body.

## Web Scraper

The scraper uses a **3-tier fallback chain** for maximum compatibility:

```
httpx (fast, lightweight)
  → curl_cffi (TLS fingerprint, bypasses Cloudflare on most sites)
  → scraper microservice with Playwright (full Chromium browser)
```

**Main RAG image** includes httpx + curl_cffi (lightweight, covers 95% of sites).
**Scraper microservice** (`scraper-service-main/`) adds Playwright for JS-heavy sites.

For non-Docker setups:

```bash
# curl_cffi (Cloudflare bypass) — recommended
pip install curl_cffi

# Playwright (JS rendering) — only if needed
pip install playwright
playwright install chromium
```

### Scrape Endpoints

**POST /api/v1/client/scrape**

```json
{
  "url": "https://example.com",
  "crawl": false,
  "max_pages": 10,
  "max_depth": 2,
  "full_site": false
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `url` | — | Target URL to scrape |
| `crawl` | `false` | Follow links on the page |
| `max_pages` | `10` | Max pages to fetch (raised to 200 in full_site mode) |
| `max_depth` | `2` | Link depth to follow (raised to 10 in full_site mode) |
| `full_site` | `false` | Smart discovery: sitemap → language variants → BFS crawl |

When `full_site=true`, the scraper:
1. Parses `sitemap.xml` (supports sub-sitemaps)
2. Discovers language variants (EN/FR/DE/ES) via hreflang tags
3. Filters out non-HTML files (`.jpg`, `.pdf`, etc.) and social share URLs
4. Scrapes URLs in parallel (5 concurrent, 2-minute cap)
5. Deduplicates via `_normalize_url()` (strips fragments, tracking params, language suffixes)

### Scraper Config (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPCRAWL_API_KEY` | — | Optional final fallback for blocked sites |
| `SCRAPER_MAX_PAGES` | `200` | Max pages in full_site mode |
| `SCRAPER_MAX_DEPTH` | `10` | Max link depth in full_site mode |

## Known Issues

- SSL cert filenames: `start.sh` generates `server.key`/`server.crt`; nginx expects `cert.pem`/`key.pem`. Symlink or copy after generation.
- `start.sh` health check targets `/health` (OCR service) instead of `/api/v1/health` (RAG API)

## Troubleshooting

```bash
# View all logs
docker compose logs -f

# Check a specific service
docker compose logs rag_api --tail=50

# Restart after config changes
docker compose down && docker compose up -d

# Full clean (destroys data)
docker compose down -v
```

| Issue | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | Missing/invalid JWT | Login at `POST /api/v1/admin/login` |
| `404` on admin routes | Not behind nginx | Use `https://localhost/` not `http://localhost:8000/` |
| OCR service `degraded` | PaddleOCR not in image | Rebuild: `docker compose build ocr_service` |
| Scraper fails on Cloudflare sites | curl_cffi not installed | `pip install curl_cffi` (included in Docker) |
| Scraper returns "HTTP 200" error | Playwright unavailable for JS-heavy sites | `pip install playwright && playwright install chromium` or set `DEEPCRAWL_API_KEY` |
| Scraper returns garbage/binary content | Cloudflare challenge not bypassed | Rebuild Docker image: `docker compose build --no-cache rag_api` |
| Carriage return in API keys | Windows CRLF in `.env` | `sed -i 's/\r$//' .env` |
