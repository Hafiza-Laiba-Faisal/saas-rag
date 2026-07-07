# Docker Compose Production Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform as a fully containerized stack using Docker Compose on a single VPS.

**Why Docker Compose?**
- Single-command deployment across any Linux VPS
- Environment parity between dev/staging/production
- Isolated services with defined resource limits
- Easy rollback via image tags
- Industry standard for small-to-medium deployments

**Timeline:** 2–4 days for initial setup, 1 day for ongoing maintenance

**Team Requirements:** 1 DevOps engineer (part-time)

**Key Risks:**
- Docker daemon resource overhead (~3–5% CPU)
- Persistent volume management for databases
- Network security between containers

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────┐
│                    VPS Instance                        │
│                                                        │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │  Nginx    │───▶│  RAG API  │───▶│    PostgreSQL    │  │
│  │  :443/80  │    │  :8000    │    │    :5432        │  │
│  └──────────┘    └────┬─────┘    └──────────────────┘  │
│        │               │                                │
│        │        ┌──────▼──────┐    ┌──────────────────┐  │
│        │        │  Qdrant     │    │     Redis        │  │
│        │        │  :6333/6334 │    │     :6379        │  │
│        │        └─────────────┘    └──────────────────┘  │
│        │               │                                │
│        │        ┌──────▼──────┐                         │
│        └───────▶│  Static     │                         │
│                 │  Frontend   │                         │
│                 └─────────────┘                         │
│                                                        │
│  Docker Network: rag_network (bridge)                   │
└──────────────────────────────────────────────────────┘
```

**Service Communication:**
- Nginx terminates SSL → proxies `/api/` to RAG API, `/` to static frontend
- RAG API connects to PostgreSQL (documents), Qdrant (vectors), Redis (cache)
- All services communicate over internal Docker network — no public ports except Nginx

---

## 3. Resource Requirements

### Minimum Viable Stack

| Service        | vCPU | RAM   | Storage | Image/Notes                  |
|---------------|------|-------|---------|------------------------------|
| RAG API       | 1    | 1 GB  | 500 MB  | Custom Dockerfile            |
| Qdrant        | 1    | 1 GB  | 5 GB    | qdrant/qdrant:latest         |
| PostgreSQL    | 1    | 1 GB  | 10 GB   | postgres:16-alpine           |
| Redis         | 0.5  | 256 MB| N/A     | redis:7-alpine               |
| Nginx         | 0.5  | 128 MB| 100 MB  | nginx:alpine                 |
| **Total**     | **4**| **3.5 GB**| **16 GB** |                          |

### Recommended Production Stack (10+ tenants, 1000+ docs/tenant)

| Service        | vCPU | RAM   | Storage | Notes                        |
|---------------|------|-------|---------|------------------------------|
| RAG API       | 2    | 2 GB  | 1 GB    | Multi-worker uvicorn         |
| Qdrant        | 2    | 4 GB  | 50 GB   | HNSW index requires RAM     |
| PostgreSQL    | 2    | 2 GB  | 50 GB   | With indexing + partitions  |
| Redis         | 1    | 512 MB| N/A     | Session + cache              |
| Nginx         | 1    | 256 MB| 100 MB  | With rate limiting           |
| **Total**     | **8**| **9 GB** | **101 GB** |                        |

---

## 4. Cost Comparison

### Estimated Monthly Cost by Provider (Recommended Stack)

| Provider      | Plan          | vCPU | RAM  | Storage | Monthly Cost | Notes                         |
|---------------|---------------|------|------|---------|-------------|-------------------------------|
| **Hetzner**   | CX32 + CAX31  | 6    | 8 GB | 80 GB   | **~€25**    | Best value in Europe          |
| **Hostinger** | VPS Premium 4 | 4    | 8 GB | 200 GB  | **~$25**    | Good global coverage          |
| **DigitalOcean** | Premium 8GB | 4    | 8 GB | 160 GB  | **~$48**    | Higher but reliable           |
| **Linode**    | Dedicated 8GB | 4    | 8 GB | 160 GB  | **~$48**    | Comparable to DO              |

### Minimum Stack Cost

| Provider      | Plan          | vCPU | RAM  | Monthly Cost |
|---------------|---------------|------|------|-------------|
| **Hetzner**   | CX22 (CCX12) | 2    | 4 GB | **~€5–10** |
| **Hostinger** | VPS Premium 2| 2    | 4 GB | **~$12**    |
| **DigitalOcean** | Basic 4GB  | 2    | 4 GB | **~$24**    |

> **Note:** All costs are for the VPS instance. Docker imposes no additional licensing fee. PostgreSQL, Redis, Qdrant are all open-source.

---

## 5. Step-by-Step Implementation

### 5.1 Prerequisites

- A Linux VPS (Ubuntu 22.04 LTS recommended)
- Domain name pointing to VPS IP
- Docker Engine 24+ and Docker Compose v2 installed
- Git access to the project repository

### 5.2 Project Restructuring for Docker

Create the following structure in the project root:

```
tenbit-rag/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── nginx/
│   └── default.conf
├── src/
│   └── rbs_rag/
└── .env.production
```

### 5.3 Dockerfile

```dockerfile
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir --prefix=/install \
        fastapi uvicorn[standard] pydantic python-multipart \
        httpx python-json-logger pillow numpy \
        pypdf openpyxl xlrd python-pptx \
        qdrant-client redis asyncpg aiosqlite

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ src/
COPY .env.production .env

EXPOSE 8000
CMD ["uvicorn", "rbs_rag.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 5.4 docker-compose.yml

```yaml
version: "3.8"

networks:
  rag_network:
    driver: bridge

volumes:
  postgres_data:
  qdrant_data:
  redis_data:
  rag_data:

services:
  postgres:
    image: postgres:16-alpine
    networks:
      - rag_network
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: rag
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rag_user -d rag"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "2G"

  qdrant:
    image: qdrant/qdrant:latest
    networks:
      - rag_network
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_ENABLED: "true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 15s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "4G"

  redis:
    image: redis:7-alpine
    networks:
      - rag_network
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "1"
          memory: "512M"

  rag_api:
    build: .
    networks:
      - rag_network
    volumes:
      - rag_data:/app/.rbs_rag
    environment:
      RAG_ENV: production
      RAG_DB_URL: postgresql+asyncpg://rag_user:${POSTGRES_PASSWORD}@postgres:5432/rag
      RAG_QDRANT_HOST: qdrant
      RAG_QDRANT_PORT: 6333
      RAG_REDIS_HOST: redis
      RAG_REDIS_PORT: 6379
      RAG_LLM_API_KEY: ${RAG_LLM_API_KEY}
      RAG_LLM_PROVIDER: ${RAG_LLM_PROVIDER:-gemini}
      RAG_LLM_MODEL: ${RAG_LLM_MODEL:-gemini-2.5-flash-lite}
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "2G"

  nginx:
    image: nginx:alpine
    networks:
      - rag_network
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
      - rag_data:/app/.rbs_rag:ro
    depends_on:
      - rag_api
    deploy:
      resources:
        limits:
          cpus: "1"
          memory: "256M"
```

### 5.5 Nginx Configuration

```nginx
server {
    listen 80;
    server_name rag.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name rag.yourdomain.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 100M;

    location /api/ {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache_bypass $http_upgrade;
    }

    location / {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 5.6 Deployment Steps

```bash
# 1. SSH into VPS
ssh root@your-vps-ip

# 2. Install Docker
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# 3. Clone repository
git clone https://github.com/your-org/tenbit-rag.git
cd tenbit-rag

# 4. Create .env.production
cat > .env.production << 'EOF'
POSTGRES_PASSWORD=generate-a-strong-password-here
RAG_LLM_API_KEY=your-gemini-or-openai-key
RAG_LLM_PROVIDER=gemini
RAG_LLM_MODEL=gemini-2.5-flash-lite
RAG_ENV=production
EOF

# 5. Get SSL certificate
docker run -it --rm -p 80:80 -v ./ssl:/etc/letsencrypt \
  certbot/certbot certonly --standalone -d rag.yourdomain.com

# 6. Start the stack
docker compose --env-file .env.production up -d

# 7. Verify
docker compose ps
docker compose logs rag_api
```

### 5.7 CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -t ghcr.io/your-org/rag-api:latest .

      - name: Push to registry
        run: |
          echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u ${{ github.actor }} --password-stdin
          docker push ghcr.io/your-org/rag-api:latest

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: root
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd /opt/tenbit-rag
            docker compose pull rag_api
            docker compose --env-file .env.production up -d rag_api
```

---

## 6. Security & Backup

### Security Measures
- Run containers as non-root user (use `user: 1000:1000` in compose)
- Database passwords stored in `.env.production` (never committed)
- Internal network only — no public ports except Nginx
- Regular `docker scan` on custom images
- Fail2ban on VPS for SSH brute force protection
- Ubuntu unattended-upgrades for security patches

### Backup Strategy

| Data           | Method                         | Frequency | Retention |
|---------------|-------------------------------|-----------|-----------|
| PostgreSQL    | `pg_dump` via cron → S3       | Daily     | 30 days   |
| Qdrant        | Snapshot API + S3 upload      | Daily     | 7 days    |
| Redis         | RDB snapshot → S3             | Hourly    | 24 hours  |
| .rbs_rag      | tar + S3 upload                | Daily     | 14 days   |

### Monitoring
- `docker compose logs --tail=100 -f`
- Prometheus node_exporter + Grafana dashboard
- Uptime monitoring with UptimeRobot (free tier)
- Alert on container restarts: `docker events` → webhook

---

## 7. Production Readiness Checklist

- [ ] Dockerfile uses multi-stage builds
- [ ] All secrets in `.env.production`, never in Dockerfile
- [ ] Health checks configured on every service
- [ ] Resource limits set on all containers
- [ ] SSL certificate configured and auto-renewing
- [ ] PostgreSQL data persisted to named volume
- [ ] Qdrant data persisted to named volume
- [ ] Nginx rate limiting configured
- [ ] Log rotation configured (Docker json-file + external)
- [ ] Backup scripts written and tested
- [ ] Monitoring endpoint responding (`/health`)
- [ ] CI/CD pipeline pushes to registry
- [ ] Rollback procedure documented
- [ ] Load test performed (minimum 50 concurrent users)
- [ ] Docker daemon configured with `live-restore: true`

---

## Appendix: Migration from SQLite to PostgreSQL

The current system uses SQLite. For production Docker deployment, migrate to PostgreSQL:

1. Dump SQLite data: `sqlite3 .rbs_rag/rag.db .dump > dump.sql`
2. Convert dialect (SQLite → PostgreSQL compatible)
3. Import to PostgreSQL: `psql -U rag_user -d rag < converted_dump.sql`
4. Update `config.json` to use `postgresql+asyncpg://` connection string
5. Verify data integrity with row counts
