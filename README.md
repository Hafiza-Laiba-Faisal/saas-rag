# TenBit RAG Platform

Multi-tenant Retrieval-Augmented Generation platform with OCR, web scraping, hybrid search, and per-tenant LLM configuration.

## Quick Start

```bash
# Full bootstrap — checks prerequisites, generates SSL, builds images, starts services
sudo ./start.sh
```

Open **https://localhost/** (accept self-signed cert warning), login with `admin` / `admin`, create a tenant with your LLM API key.

## Services

| Container | Purpose |
|-----------|---------|
| tenbit-rag-api | RAG engine + admin/client dashboards |
| tenbit-nginx | Reverse proxy (HTTP -> HTTPS redirect, rate limiting) |
| tenbit-qdrant | Vector database (HNSW ANN + BM25 hybrid search) |
| tenbit-redis | Caching and rate limiting |
| tenbit-ocr | OCR microservice (PaddleOCR local, optional Mistral cloud) |
| tenbit-scraper | Web scraper microservice (httpx/BS4, optional DeepCrawl for Cloudflare) |

## Access

| URL | Description |
|-----|-------------|
| https://localhost/ | Admin dashboard (JWT login) |
| https://localhost/client | Client dashboard (API key login) |
| https://localhost/widget?api_key=xxx | Embeddable chat widget |
| https://localhost/api/v1/chat | Client chat endpoint (X-API-Key header) |
| https://localhost/api/v1/health | Health check |

## Architecture

- **Multi-tenant isolation** — each tenant has its own SQLite DB, document directory, and Qdrant collection prefix
- **Hybrid search** — Qdrant ANN (dense) + BM25 (sparse) with RRF fusion
- **Chunking** — hierarchical with optional semantic chunking
- **Document types** — txt, pdf, images (png/jpg/gif/bmp/tiff/webp/svg), html, docx, xlsx, pptx, csv, json, xml, epub, rtf, md
- **LLM providers** — Gemini, OpenAI-compatible (including Mistral, Groq, Together, etc.), Anthropic
- **OCR pipeline** — PaddleOCR (local, no API key) -> Mistral OCR (cloud, optional)
- **Auth** — JWT-based admin auth (username: `admin`, password from `RAG_ADMIN_PASSWORD`), X-API-Key for client endpoints
- **System prompt** — customizable per tenant, overridable per chat request

## Configuration

Single `.env` file at project root. Key variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RAG_ENCRYPTION_KEY` | Yes | -- | Fernet key for encrypting API keys at rest |
| `RAG_ADMIN_JWT_SECRET` | Yes | -- | JWT signing secret (32+ chars) |
| `RAG_ADMIN_PASSWORD` | No | `admin` | Admin dashboard password |
| `DEEPCRAWL_API_KEY` | No | -- | Cloudflare bypass for scraper |

See [docs/SETUP.md](docs/SETUP.md) for full setup and API reference.
