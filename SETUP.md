# TenBit RAG Platform — Complete Setup Guide

> **Version:** 1.0 | **Last Updated:** 2025 | **Target:** Enterprise Production Deployment

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Quick Start (Development)](#2-quick-start-development)
3. [Detailed Installation](#3-detailed-installation)
4. [Service Configuration](#4-service-configuration)
5. [Running the Platform](#5-running-the-platform)
6. [Verification & Testing](#6-verification--testing)
7. [Production Deployment](#7-production-deployment)
8. [Troubleshooting](#8-troubleshooting)
9. [Maintenance](#9-maintenance)

---

## 1. System Requirements

### 1.1 Minimum Hardware (Development)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 4 cores | 8+ cores |
| **RAM** | 8 GB | 16+ GB |
| **Disk** | 10 GB free | 50+ GB SSD |
| **GPU** | Optional (for BGE-M3) | NVIDIA GPU 8GB+ VRAM |

### 1.2 Minimum Hardware (Production)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 8 cores | 16+ cores |
| **RAM** | 16 GB | 32+ GB |
| **Disk** | 100 GB SSD | 500+ GB NVMe |
| **GPU** | NVIDIA GPU 8GB+ VRAM | NVIDIA A10G/H100 |

### 1.3 Software Dependencies

| Software | Version | Purpose |
|----------|---------|---------|
| **Python** | 3.11+ | Core runtime |
| **Node.js** | 18+ | Frontend tooling (optional) |
| **Git** | 2.30+ | Version control |
| **Docker** | 24+ | Container deployment |
| **Docker Compose** | 2.20+ | Multi-container orchestration |
| **uv** | Latest | Fast Python package manager (recommended) |

### 1.4 External API Keys (Optional but Recommended)

| Service | Key | Purpose | Required |
|---------|-----|---------|----------|
| **Mistral AI** | `MISTRAL_API_KEY` | Cloud OCR (primary) | No (local fallback) |
| **DeepCrawl** | `DEEPCRAWL_API_KEY` | Cloudflare bypass | No |
| **Google AI** | `GEMINI_API_KEY` | LLM (Gemini) | Yes |
| **OpenAI** | `OPENAI_API_KEY` | LLM (or compatible) | LLM (OpenAI/Groq/etc.) | Alternative |
| **Anthropic** | `ANTHROPIC_API_KEY` | LLM (Claude) | Alternative |

---

## 2. Quick Start

### 2.0 Docker (Recommended — Single Command)

```bash
cd C:\Root\Projects\TenBit\RAG

# Edit .env to set your LLM API key, then:
docker compose up -d

# Full stack including optional OCR/Scraper:
# docker compose --profile all up -d
```

Access: **http://localhost** (admin dashboard via Nginx on port 80)

See [RUN_GUIDE.md](RUN_GUIDE.md) for detailed Docker instructions.

### 2.1 Manual Development Setup (3 Terminals)

For development without Docker, use the manual setup below:

#### Terminal 1: OCR Service (Port 8001)
```bash
cd /projects/TenBit/RAG/ocr-service-main
python -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env - add MISTRAL_API_KEY if available
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

#### Terminal 2: Scraper Service (Port 8002)
```bash
cd /projects/TenBit/RAG/scraper-service-main
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env - add DEEPCRAWL_API_KEY if available
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

#### Terminal 3: RAG Core + Dashboard (Port 8100)
```bash
cd /projects/TenBit/RAG
export PYTHONPATH="src"
python -m pip install -e .
rag init
python -m rbs_rag.web_run
```

### 2.2 Access Dashboard

- **Docker mode**: http://localhost (port 80, via Nginx)
- **Manual mode**: http://localhost:8100 (direct to uvicorn)

---

## 3. Detailed Installation

### 3.1 RAG Core Installation

#### Using uv (Recommended - Faster)

```bash
cd /projects/TenBit/RAG

# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# Create virtual environment and install
uv venv
source .venv/bin/activate
uv pip install -e ".[local-ml,dev]"
```

#### Using pip (Standard)

```bash
cd /projects/TenBit/RAG

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install package with optional dependencies
pip install -e ".[local-ml,dev]"

# Or minimal install (no local ML)
pip install -e .
```

#### Optional Dependency Groups

| Extra | Packages | Use Case |
|-------|----------|----------|
| `local-ml` | `sentence-transformers`, `flag-embedding`, `fastembed` | Local embeddings/reranking |
| `pdf` | `pypdf`, `pymupdf` | Enhanced PDF parsing |
| `dev` | `pytest`, `black`, `ruff`, `mypy`, `pre-commit` | Development tools |
| `all` | All of the above | Full development setup |

### 3.2 OCR Service Installation

```bash
cd /projects/TenBit/RAG/ocr-service-main

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install with uv (faster)
uv pip install -e .

# Or with pip
pip install -e .

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update && sudo apt-get install -y \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgl1-mesa-glx poppler-utils tesseract-ocr \
    libreoffice  # For PPTX/XLSX conversion
```

#### GPU Support (Optional)

```bash
# For CUDA support with PaddleOCR
pip install paddlepaddle-gpu -f https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html

# Or install onnxruntime-gpu
pip install onnxruntime-gpu
```

### 3.3 Scraper Service Installation

```bash
cd /projects/TenBit/RAG/scraper-service-main

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update && sudo apt-get install -y \
    ffmpeg \
    chromium-browser \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils
```

---

## 4. Service Configuration

### 4.1 RAG Core Configuration

#### 4.1.1 Initialize Configuration

```bash
cd /projects/TenBit/RAG
export PYTHONPATH="src"
rag init
```

This creates `.rbs_rag/config.json` with defaults.

#### 4.1.2 Configuration Structure

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
    "model": "BAAI/bge-small-en-v1.5"
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

#### 4.1.3 Environment Variables

Create `.env` in project root:

```env
# LLM API Key (required)
RAG_LLM_API_KEY=your_gemini_or_openai_key_here

# Optional: Override config values
RAG_EMBEDDING_PROVIDER=hash
RAG_CHUNK_MAX_TOKENS=320
RAG_RETRIEVAL_TOP_K=20

# Admin JWT Secret (for production)
ADMIN_JWT_SECRET=your-super-secret-jwt-key-min-32-chars

# CORS Origins (production)
CORS_ORIGINS=http://localhost:3000,https://yourdomain.com
```

#### 4.1.4 LLM Provider Configurations

**Gemini (Default):**
```json
{
  "llm": {
    "provider": "gemini",
    "api_key": "${RAG_LLM_API_KEY}",
    "model": "gemini-2.5-flash-lite",
    "base_url": "https://generativelanguage.googleapis.com/v1beta",
    "fallback_models": ["gemini-2.5-flash"]
  }
}
```

**OpenAI / Compatible (Groq, OpenRouter, Together, Fireworks):**
```json
{
  "llm": {
    "provider": "openai_compatible",
    "api_key": "${RAG_LLM_API_KEY}",
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1"
  }
}
```

**Anthropic Claude:**
```json
{
  "llm": {
    "provider": "anthropic",
    "api_key": "${RAG_LLM_API_KEY}",
    "model": "claude-3-5-sonnet-20241022",
    "base_url": "https://api.anthropic.com/v1"
  }
}
```

### 4.2 OCR Service Configuration

#### 4.2.1 Environment File

```bash
cd /projects/TenBit/RAG/ocr-service-main
cp .env.example .env
```

#### 4.2.2 Configuration Options

```env
# Required for cloud OCR (optional - has local fallback)
MISTRAL_API_KEY=your_mistral_key_here

# Server
HOST=0.0.0.0
PORT=8001
LOG_LEVEL=INFO

# File Limits
MAX_FILE_SIZE_MB=50

# OCR Languages (PaddleOCR)
OCR_LANGUAGES=en,ur,ar

# GPU Acceleration
USE_GPU=false

# PDF Processing
PAGE_RENDER_DPI=150
MIN_TEXT_CHARS_THRESHOLD=20
MIN_IMAGE_DPI=150

# API Authentication (optional)
OCR_API_KEY=your_api_key_for_auth

# Sentry (optional)
SENTRY_DSN=your_sentry_dsn
```

#### 4.2.3 Language Codes for PaddleOCR

| Language | Code | Language | Code |
|----------|------|----------|------|
| English | `en` | Arabic | `ar` |
| Urdu | `ur` | Chinese (Simplified) | `ch` |
| French | `fr` | German | `german` |
| Spanish | `es` | Japanese | `japan` |
| Korean | `korean` | Russian | `ru` |

Multiple languages: `OCR_LANGUAGES=en,ar,ur`

### 4.3 Scraper Service Configuration

#### 4.3.1 Environment File

```bash
cd /projects/TenBit/RAG/scraper-service-main
cp .env.example .env
```

#### 4.3.2 Configuration Options

```env
# Optional: DeepCrawl API for Cloudflare bypass
DEEPCRAWL_API_KEY=your_deepcrawl_key

# Server
HOST=0.0.0.0
PORT=8002
APP_TITLE="Scraper Service"
APP_VERSION="1.0.0"

# HTTP Client Limits
MAX_CONNECTIONS=100
MAX_KEEPALIVE_CONNECTIONS=20

# Rate Limiting (requests per second per domain)
DEFAULT_RATE_LIMIT=2.0

# Retry Policy
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY=1.0
RETRY_MAX_DELAY=30.0
```

---

## 5. Running the Platform

### 5.1 Development Mode (3 Services)

#### Option A: Using Process Manager (Recommended)

Create `Procfile` in project root:
```
ocr: cd ocr-service-main && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8001
scraper: cd scraper-service-main && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8002
rag: export PYTHONPATH=src && python -m rbs_rag.web_run
```

Run with `honcho` or `foreman`:
```bash
pip install honcho
honcho start
```

#### Option B: Using tmux (Linux/macOS)

```bash
tmux new-session -d -s tenbit-rag

# Window 1: OCR
tmux send-keys -t tenbit-rag:0 'cd /projects/TenBit/RAG/ocr-service-main && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8001 --reload' Enter

# Window 2: Scraper
tmux new-window -t tenbit-rag -n scraper
tmux send-keys -t tenbit-rag:scraper 'cd /projects/TenBit/RAG/scraper-service-main && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload' Enter

# Window 3: RAG
tmux new-window -t tenbit-rag -n rag
tmux send-keys -t tenbit-rag:rag 'cd /projects/TenBit/RAG && export PYTHONPATH=src && python -m rbs_rag.web_run' Enter

# Attach
tmux attach -t tenbit-rag
```

#### Option C: Windows (PowerShell)

```powershell
# Terminal 1: OCR
cd C:\projects\TenBit\RAG\ocr-service-main
.\venv\Scripts\Activate.ps1
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2: Scraper
cd C:\projects\TenBit\RAG\scraper-service-main
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# Terminal 3: RAG
cd C:\projects\TenBit\RAG
$env:PYTHONPATH="src"
python -m rbs_rag.web_run
```

### 5.2 Production Mode (Docker Compose)

#### 5.2.1 Create Docker Compose File

```yaml
# docker-compose.yml
version: '3.8'

services:
  # Vector Database
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    deploy:
      resources:
        limits:
          memory: 4G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Cache & Rate Limiting
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Primary Database
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: tenbit_rag
      POSTGRES_USER: tenbit
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tenbit -d tenbit_rag"]
      interval: 10s
      timeout: 5s
      retries: 5

  # OCR Service
  ocr-service:
    build:
      context: ./ocr-service-main
      dockerfile: Dockerfile
    ports:
      - "8001:8000"
    environment:
      - MISTRAL_API_KEY=${MISTRAL_API_KEY}
      - OCR_API_KEY=${OCR_API_KEY}
      - LOG_LEVEL=INFO
      - USE_GPU=false
    deploy:
      resources:
        limits:
          memory: 2G
    depends_on:
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Scraper Service
  scraper-service:
    build:
      context: ./scraper-service-main
      dockerfile: Dockerfile
    ports:
      - "8002:8000"
    environment:
      - DEEPCRAWL_API_KEY=${DEEPCRAWL_API_KEY}
      - LOG_LEVEL=INFO
    volumes:
      - scraper_downloads:/app/downloads
    deploy:
      resources:
        limits:
          memory: 4G
    depends_on:
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/docs"]
      interval: 30s
      timeout: 10s
      retries: 3

  # RAG API + Dashboard
  rag-api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8100:8100"
    environment:
      - PYTHONPATH=/app/src
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://tenbit:${DB_PASSWORD}@postgres/tenbit_rag
      - RAG_LLM_API_KEY=${RAG_LLM_API_KEY}
      - ADMIN_JWT_SECRET=${ADMIN_JWT_SECRET}
      - CORS_ORIGINS=${CORS_ORIGINS}
      - OCR_SERVICE_URL=http://ocr-service:8000
      - SCRAPER_SERVICE_URL=http://scraper-service:8000
    deploy:
      resources:
        limits:
          memory: 4G
    depends_on:
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ocr-service:
        condition: service_healthy
      scraper-service:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8100/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Reverse Proxy (nginx)
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - rag-api
      - ocr-service
      - scraper-service

volumes:
  qdrant_data:
  redis_data:
  postgres_data:
  scraper_downloads:
```

#### 5.2.2 Create Nginx Config

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream rag_api {
        server rag-api:8100;
    }
    
    upstream ocr_service {
        server ocr-service:8000;
    }
    
    upstream scraper_service {
        server scraper-service:8000;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=chat:10m rate=5r/s;

    server {
        listen 80;
        server_name yourdomain.com;

        # Redirect HTTP to HTTPS
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name yourdomain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # RAG API
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://rag_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
            proxy_send_timeout 120s;
        }

        # Chat Streaming (SSE)
        location /api/v1/tenants/ {
            limit_req zone=chat burst=10 nodelay;
            proxy_pass http://rag_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_cache off;
            proxy_buffering off;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }

        # OCR Service
        location /ocr/ {
            proxy_pass http://ocr_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 300s;
            client_max_body_size 100M;
        }

        # Scraper Service
        location /crawl/ {
            proxy_pass http://scraper_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 300s;
        }

        location /scrape/ {
            proxy_pass http://scraper_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 300s;
        }

        location /db/ {
            proxy_pass http://scraper_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # Dashboard (Static Files)
        location / {
            proxy_pass http://rag_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # WebSocket for future use
        location /ws/ {
            proxy_pass http://rag_api;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }
}
```

#### 5.2.3 Deploy

```bash
# Create environment file
cat > .env << EOF
DB_PASSWORD=your_secure_postgres_password
MISTRAL_API_KEY=your_mistral_key
DEEPCRAWL_API_KEY=your_deepcrawl_key
RAG_LLM_API_KEY=your_llm_key
ADMIN_JWT_SECRET=your_super_secret_jwt_key_min_32_chars_long
CORS_ORIGINS=https://yourdomain.com
EOF

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Scale services (if needed)
docker-compose up -d --scale rag-api=3
```

---

## 6. Verification & Testing

### 6.1 Health Checks

```bash
# RAG Core
curl http://localhost:8100/health

# OCR Service
curl http://localhost:8001/health

# Scraper Service
curl http://localhost:8002/docs
```

### 6.2 API Testing

#### Test RAG Chat
```bash
# Create tenant first (via dashboard or API)
curl -X POST http://localhost:8100/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test-tenant",
    "name": "Test Tenant",
    "llm_provider": "gemini",
    "llm_model": "gemini-2.5-flash-lite",
    "llm_api_key": "your_api_key",
    "embedding_provider": "hash"
  }'

# Upload document
curl -X POST http://localhost:8100/api/v1/tenants/test-tenant/documents \
  -F "file=@./test.pdf" \
  -F "kb_id=default"

# Trigger ingestion
curl -X POST http://localhost:8100/api/v1/tenants/test-tenant/ingest

# Chat
curl -X POST http://localhost:8100/api/v1/tenants/test-tenant/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is this document about?", "session_id": "test-session"}'
```

#### Test OCR Service
```bash
# OCR a PDF
curl -X POST http://localhost:8001/ocr/pdf \
  -F "file=@./document.pdf"

# OCR an image
curl -X POST http://localhost:8001/ocr/image \
  -F "file=@./image.png"

# Batch OCR
curl -X POST http://localhost:8001/ocr/batch \
  -F "files=@./doc1.pdf" \
  -F "files=@./doc2.png"
```

#### Test Scraper Service
```bash
# Single page crawl
curl -X POST http://localhost:8002/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "format": "json"}'

# Recursive crawl
curl -X POST http://localhost:8002/crawl/recursive \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.example.com",
    "max_depth": 3,
    "max_pages": 50
  }'

# Check crawl status
curl http://localhost:8002/crawl/recursive/status/{job_id}
```

### 6.3 Run Unit Tests

```bash
# RAG Core tests
cd /projects/TenBit/RAG
export PYTHONPATH="src"
python -m unittest discover -s tests -v

# OCR Service tests
cd /projects/TenBit/RAG/ocr-service-main
source venv/bin/activate
pytest tests/ -v

# Scraper Service tests
cd /projects/TenBit/RAG/scraper-service-main
source venv/bin/activate
pytest tests/ -v
```

---

## 7. Production Deployment

### 7.0 Docker Deployment (Recommended)

```bash
# 1. Copy project to production server
# 2. Configure .env
nano .env

# 3. Start all services
docker compose up -d

# 4. (Optional) Enable OCR + Scraper microservices
# docker compose --profile all up -d
```

Access: **http://your-server-ip** (port 80)

For HTTPS:
```bash
# 1. Place SSL certs
mkdir -p nginx/ssl
# Copy fullchain.pem and privkey.pem into nginx/ssl/

# 2. Update nginx/nginx.conf to add listen 443 ssl;
#    (see comments in config for SSL directives)

# 3. Restart nginx
docker compose restart nginx

# 4. Set HTTPS_PORT=443 in .env
```

### 7.1 Pre-Deployment Checklist

- [ ] All API keys configured in `.env`
- [ ] SSL certificates obtained and placed in `./nginx/ssl/`
- [ ] Domain DNS configured
- [ ] CORS origins configured (`RAG_CORS_ORIGINS` in `.env`)
- [ ] Backup strategy defined (volumes: `rag_data`, `qdrant_data`, `redis_data`)
- [ ] Monitoring/alerting configured
- [ ] Load testing completed

### 7.2 SSL Certificate Setup

```bash
# Using Let's Encrypt (Certbot)
sudo certbot certonly --standalone -d yourdomain.com

# Copy to nginx/ssl directory
mkdir -p ./nginx/ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ./nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ./nginx/ssl/key.pem
sudo chown $USER:$USER ./nginx/ssl/*.pem

# Update nginx.conf to enable SSL (add listen 443 ssl; and ssl_* directives)
```

### 7.3 Database Migration (SQLite → PostgreSQL)

```bash
# The admin database will auto-migrate on first PostgreSQL connection
# For tenant databases, run migration script:

cd /projects/TenBit/RAG
python scripts/migrate_to_postgres.py \
  --sqlite-root .rbs_rag/tenants \
  --postgres-url postgresql://tenbit:pass@localhost/tenbit_rag
```

### 7.4 Qdrant Migration (SQLite → Qdrant)

```bash
# After Qdrant is running, migrate existing embeddings:
cd /projects/TenBit/RAG
python scripts/migrate_to_qdrant.py \
  --sqlite-root .rbs_rag/tenants \
  --qdrant-url http://localhost:6333
```

---

## 8. Troubleshooting

### 8.1 Common Issues

#### Port Already in Use
```bash
# Find process using port
lsof -i :8100  # or :8001, :8002

# Kill process
kill -9 <PID>
```

#### Module Import Errors
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH="/projects/TenBit/RAG/src"

# Or install in development mode
pip install -e /projects/TenBit/RAG
```

#### OCR Service: Mistral API Key Missing
```bash
# Check .env file
cat /projects/TenBit/RAG/ocr-service-main/.env

# Service will fallback to PaddleOCR automatically
# Check logs: "Using fallback engine: PaddleOCREngine"
```

#### Scraper Service: Playwright Not Installed
```bash
cd /projects/TenBit/RAG/scraper-service-main
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

#### Qdrant Connection Refused
```bash
# Check Qdrant is running
curl http://localhost:6333/health

# Check Docker
docker ps | grep qdrant

# Restart
docker-compose restart qdrant
```

#### Memory Issues During Ingestion
```bash
# Reduce batch size in config
# .rbs_rag/config.json:
{
  "chunking": {
    "max_tokens": 256,
    "overlap_tokens": 32
  }
}

# Or increase swap
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 8.2 Log Locations

| Service | Log Location |
|---------|--------------|
| RAG Core | Console output (stdout) |
| OCR Service | Console + `ocr-service-main/logs/` |
| Scraper Service | Console + `scraper-service-main/logs/` |
| Docker | `docker-compose logs -f <service>` |

### 8.3 Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Or in .env
LOG_LEVEL=DEBUG
```

---

## 9. Maintenance

### 9.1 Regular Tasks

| Task | Frequency | Command |
|------|-----------|---------|
| **Backup databases** | Daily | `./scripts/backup.sh` |
| **Clean old sessions** | Weekly | `curl -X POST /api/v1/tenants/{id}/sessions/purge` |
| **Rotate logs** | Weekly | `logrotate /etc/logrotate.d/tenbit-rag` |
| **Update dependencies** | Monthly | `pip list --outdated` |
| **Check disk space** | Daily | `df -h` |
| **Monitor Qdrant collections** | Weekly | `curl http://qdrant:6333/collections` |

### 9.2 Backup Script

```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="/backups/tenbit-rag/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup admin database
cp /projects/TenBit/RAG/.rbs_rag/admin.db "$BACKUP_DIR/"

# Backup tenant databases
cp -r /projects/TenBit/RAG/.rbs_rag/tenants "$BACKUP_DIR/"

# Backup Qdrant (if using local storage)
docker exec qdrant qdrant-cli backup --output /tmp/qdrant_backup
docker cp qdrant:/tmp/qdrant_backup "$BACKUP_DIR/qdrant_backup"

# Compress
tar -czf "$BACKUP_DIR.tar.gz" -C "$BACKUP_DIR" .
rm -rf "$BACKUP_DIR"

# Keep last 30 days
find /backups/tenbit-rag -name "*.tar.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_DIR.tar.gz"
```

### 9.3 Log Rotation Config

```bash
# /etc/logrotate.d/tenbit-rag
/projects/TenBit/RAG/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload tenbit-rag > /dev/null 2>&1 || true
    endscript
}
```

### 9.4 Updating Services

```bash
# Pull latest images
docker-compose pull

# Rebuild custom images
docker-compose build --no-cache

# Rolling update (zero downtime)
docker-compose up -d --no-deps rag-api
docker-compose up -d --no-deps ocr-service
docker-compose up -d --no-deps scraper-service
```

---

## Appendix: Useful Commands Reference

### Service Management
```bash
# Start all (Docker)
docker-compose up -d

# Stop all
docker-compose down

# Restart single service
docker-compose restart rag-api

# View logs
docker-compose logs -f rag-api

# Execute command in container
docker-compose exec rag-api bash
```

### Database Operations
```bash
# Access PostgreSQL
docker-compose exec postgres psql -U tenbit -d tenbit_rag

# Access SQLite
sqlite3 .rbs_rag/admin.db

# Qdrant CLI
docker-compose exec qdrant qdrant-cli collections list
```

### Monitoring
```bash
# Qdrant metrics
curl http://localhost:6333/metrics

# Redis info
docker-compose exec redis redis-cli INFO

# System resources
docker stats
```

---

*End of Setup Guide*