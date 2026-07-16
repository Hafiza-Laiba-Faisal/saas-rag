# On-Premises Windows Server Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform on your own private Windows VM server — running on-premises or in your data center — with internet accessibility via reverse proxy and full API integration support for external clients.

**Why On-Premises?**
- **Full control** over hardware, data, and uptime — no third-party cloud dependency
- **No monthly hosting fees** — pay only for electricity, domain, and internet bandwidth
- **Unlimited resources** — 16 GB RAM expandable, 200 GB+ storage expandable, high-speed processor
- **Data sovereignty** — all documents, vectors, and conversation logs stay on your hardware
- **API integrations** — external clients can integrate via REST API with tenant-level API key auth
- **Existing infrastructure** — you already have the server running, no new hardware needed

**Total Monthly Cost: €0–15** (domain name renewal + optional static IP)

**Timeline:** 1–2 days for full deployment

**Team Requirements:** 1 Developer/Admin

**Key Risks:**
- Public IP and port forwarding required for internet access (security consideration)
- Windows VM must be always-on for production availability
- Docker Desktop requires paid license for enterprise teams (or use WSL2 backend)

---

## 2. Architecture

### 2.1 High-Level Architecture

```mermaid
graph TB
    subgraph "Internet"
        CLIENT[External Client<br/>Browser / App]
        PARTNER[Partner Integrations<br/>API Consumers]
        DNS[DNS: rag.yourdomain.com]
    end

    subgraph "Your Windows VM"
        subgraph "Hyper-V / VMware VM"
            direction TB
            WIN[Windows Server 2022<br/>16GB RAM · 200GB+ SSD · High-Speed CPU]

            subgraph "WSL2 (Ubuntu 22.04)"
                direction TB
                DOCKER[Docker Engine]
                NGINX_CONTAINER[Nginx<br/>:443 → :8000<br/>Reverse Proxy + SSL]
                RAG_CONTAINER[RAG API<br/>:8000<br/>FastAPI + Uvicorn]
                QDRANT_CONTAINER[Qdrant<br/>:6333<br/>Vector Database]
                REDIS_CONTAINER[Redis<br/>:6379<br/>Cache + Sessions]
                POSTGRES_CONTAINER[PostgreSQL<br/>:5432<br/>Document Store]
            end

            subgraph "Windows Native"
                TUNNEL[Optional: Cloudflare Tunnel<br/>For Zero-Trust Access]
            end
        end
    end

    subgraph "External Services"
        LLM_API[Gemini / OpenAI / Anthropic API]
        BACKUP[Backup Destination<br/>External HDD / S3]
    end

    CLIENT -->|HTTPS :443| DNS
    DNS -->|Public IP| WIN
    WIN -->|Port Forward :443| NGINX_CONTAINER
    NGINX_CONTAINER --> RAG_CONTAINER

    RAG_CONTAINER --> POSTGRES_CONTAINER
    RAG_CONTAINER --> QDRANT_CONTAINER
    RAG_CONTAINER --> REDIS_CONTAINER

    RAG_CONTAINER -->|API Calls| LLM_API
    RAG_CONTAINER -->|Backups| BACKUP

    PARTNER -->|API Key Auth| DNS
```

### 2.2 Network Topology

```mermaid
graph TB
    subgraph "Your Network"
        ROUTER[Router / Firewall]
        PORT[Port Forwarding<br/>WAN :443 → VM :443]
        VM[Windows VM<br/>192.168.1.100]

        subgraph "VM Internal"
            WSL2_PROXY[WSL2 :443<br/>mapped from Windows :443]
            DOCKER_NET[Docker Bridge Network]
            NGINX[Nginx Container<br/>:443 → :8000]
            API[RAG API Container<br/>:8000]
        end
    end

    subgraph "External"
        USER[User Browser<br/>https://rag.domain.com]
    end

    USER -->|HTTPS| ROUTER
    ROUTER --> PORT
    PORT --> VM
    VM -->|Windows Port Proxy| WSL2_PROXY
    WSL2_PROXY --> DOCKER_NET
    DOCKER_NET -->|Ingress| NGINX
    NGINX -->|Proxy Pass| API
```

### 2.3 API Integration Flow (For External Clients)

```mermaid
sequenceDiagram
    participant Client as External Client
    participant DNS as rag.domain.com
    participant Nginx as Nginx Reverse Proxy
    participant API as RAG API
    participant LLM as LLM Provider

    Note over Client: Has API Key: rbs_rag_sk_xxxxx

    Client->>DNS: POST /api/v1/chat
    Note right of Client: Headers:<br/>X-API-Key: sk_xxxxx<br/>Content-Type: application/json

    DNS->>Nginx: Forward to :443
    Nginx->>API: Proxy to :8000

    API->>API: Validate X-API-Key
    API->>API: Lookup tenant by key
    API->>API: Rate limit check
    API->>API: Process query

    API->>LLM: Generate response
    LLM-->>API: Response text

    API-->>Client: 200 OK
    Note right of Client: {<br/>  "answer": "...",<br/>  "citations": [...]<br/>}
```

---

## 3. Approach Analysis: Three Deployment Strategies

### Strategy A: WSL2 + Docker Containers (Recommended)

| Aspect | Details |
|--------|---------|
| **Description** | Install WSL2 (Ubuntu), run Docker Engine inside WSL, deploy all services as Docker containers via docker-compose |
| **Isolation** | ✅ Excellent — each service in its own container |
| **Performance** | ✅ Near-native Linux performance via WSL2 Hyper-V backend |
| **Windows Integration** | ✅ Files accessible from both Windows and WSL, ports exposed to Windows host |
| **Management** | ✅ `docker compose up/down` — same commands as Linux |
| **Persistence** | ✅ Volumes stored on Windows filesystem (ext4.vhdx) |
| **Learning Curve** | Low — same as Linux Docker deployment |
| **Docker License** | Use Docker Engine (free) — NOT Docker Desktop (paid for enterprise) |

### Strategy B: Native Windows Installation (Alternative)

| Aspect | Details |
|--------|---------|
| **Description** | Install PostgreSQL, Redis (Memurai), Qdrant, and Python directly on Windows, run the app as a Windows Service |
| **Isolation** | ❌ Poor — all services in same OS, no resource isolation |
| **Performance** | ✅ No virtualization overhead |
| **Management** | ❌ Each service has different Windows setup — complex |
| **Qdrant** | ⚠️ Windows binary exists but less tested |
| **Redis** | ⚠️ Use Memurai (Windows Redis-compatible, free tier limited) |
| **Process Management** | ❌ Need NSSM or similar for Windows services |
| **Learning Curve** | Medium — non-standard setup |
| **Recommendation** | ❌ Only if Docker/WSL2 is blocked by policy |

### Strategy C: Docker Desktop (Not Recommended)

| Aspect | Details |
|--------|---------|
| **Description** | Install Docker Desktop for Windows with WSL2 backend |
| **Isolation** | ✅ Good — same containers as Strategy A |
| **Performance** | ✅ Good — same WSL2 backend |
| **Management** | ✅ Same docker-compose approach |
| **License** | ❌ **Paid** for enterprise teams ($$$ per developer) |
| **Overhead** | ❌ Docker Desktop adds GUI, VM management, auto-updater |
| **Recommendation** | ❌ Use Strategy A instead — Docker Engine in WSL2 is free |

### Strategy Comparison

| Criterion | A: WSL2 + Docker Engine | B: Native Windows | C: Docker Desktop |
|-----------|------------------------|------------------|------------------|
| Cost | Free | Free | Paid (enterprise) |
| Isolation | ✅ Excellent | ❌ Poor | ✅ Excellent |
| Setup Time | 1–2 hours | 3–5 hours | 30 min |
| Maintenance | Low | Medium | Low |
| Windows Updates | ✅ WSL survives reboot | ✅ Native | ⚠️ Can break |
| Performance | 98% native | 100% native | 98% native |
| Portability | ✅ docker-compose | ❌ Windows-only | ✅ docker-compose |
| Documentation Fit | ✅ Matches Doc 1 | ❌ Custom | ✅ Matches Doc 1 |

---

## 4. Resource Requirements

### Current VM Specs vs. Requirements

| Resource | Your VM | Required (Min) | Required (Recommended) | Headroom |
|----------|---------|---------------|----------------------|----------|
| **vCPU** | High-speed | 2 cores | 4 cores | ✅ Ample |
| **RAM** | 16 GB | 4 GB | 8 GB | ✅ 50%+ free |
| **Storage** | 200 GB (expandable) | 20 GB | 50 GB | ✅ 75%+ free |
| **OS** | Windows Server/Pro | Any Windows 10/11/Server | — | ✅ |

### Per-Container Resource Allocation

| Container | vCPU Request | RAM Request | RAM Limit | Storage |
|-----------|-------------|-------------|-----------|---------|
| RAG API | 1 core | 1 GB | 2 GB | 1 GB (code) |
| PostgreSQL | 1 core | 1 GB | 2 GB | 20 GB (data) |
| Qdrant | 1 core | 1 GB | 2 GB | 10 GB (vectors) |
| Redis | 0.5 core | 256 MB | 512 MB | — |
| Nginx | 0.25 core | 128 MB | 256 MB | — |
| **Total** | **3.75 cores** | **~3.5 GB** | **~7 GB** | **~31 GB** |

### Capacity on Your VM

| Metric | Capacity | Notes |
|--------|----------|-------|
| Max tenants | 50+ | Limited by RAM per tenant sessions |
| Max documents | 50,000+ | 200 GB storage = ~4M documents at 50KB avg |
| Max chunks | 500,000+ | Qdrant handles millions on 2 GB RAM |
| Concurrent queries | 20–50 | Uvicorn workers + PostgreSQL pool |
| Concurrent uploads | 5–10 | Writes to Qdrant + PostgreSQL simultaneously |

---

## 5. Cost Breakdown

### Monthly Operating Costs

| Item | Cost | Notes |
|------|------|-------|
| **Server Hardware** | €0 | Already owned |
| **Electricity** | ~€5–15/mo | Depending on local rates, 24/7 operation |
| **Domain Name** | ~€10–15/year | e.g., rag.yourcompany.com |
| **Static Public IP** | ~€0–10/mo | Check with ISP — some include, some charge |
| **SSL Certificate** | €0 | Let's Encrypt (auto-renewing, free) |
| **Docker License** | €0 | Docker Engine (Community) is free |
| **Windows License** | €0 | Already licensed |
| **LLM API** | ~$5–50/mo | Pay-per-token to Gemini/OpenAI |
| **Backup Storage** | €0 | External HDD or NAS |
| **Total** | **~€10–75/mo** | Mostly LLM API costs |

### Comparison to Cloud

| Provider | Similar Spec | Monthly Cost | Your Savings |
|----------|-------------|-------------|--------------|
| **Your VM** | 16 GB RAM, 200 GB SSD, fast CPU | **~€10–15** | — |
| Hetzner | CX32 (4 vCPU, 8 GB, 80 GB) | ~€13 | Comparable |
| DigitalOcean | Premium 16 GB (4 vCPU, 16 GB) | ~$96 | **~6× more** |
| AWS | t3.large (2 vCPU, 8 GB) | ~$69 + storage | **~5× more** |
| Hostinger | VPS Premium 4 (4 vCPU, 8 GB) | ~$25 | **~2× more** |

> **Your on-premises approach saves €25–80+/month compared to equivalent cloud VPS.**
>
> With 16 GB RAM and expandable storage, your VM is equivalent to a $100–150/mo cloud instance.

---

## 6. Step-by-Step Implementation

### Phase 1: WSL2 Setup on Windows VM

```powershell
# ========================
# Windows VM Setup
# ========================

# 1. Enable WSL2 (Run as Administrator in PowerShell)
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Restart-Computer

# 2. After reboot, set WSL2 as default
wsl --set-default-version 2

# 3. Install Ubuntu 22.04 LTS
wsl --install -d Ubuntu-22.04

# 4. Set memory limit for WSL2 (prevents Linux from eating all 16 GB)
# Create/edit: %USERPROFILE%\.wslconfig
@"
[wsl2]
memory=8GB
processors=4
localhostForwarding=true
"@ | Out-File -FilePath "$env:USERPROFILE\.wslconfig" -Encoding utf8

# 5. Restart WSL
wsl --shutdown
wsl ~ -d Ubuntu-22.04
```

```bash
# ========================
# Inside WSL2 (Ubuntu)
# ========================

# 6. Update Ubuntu
sudo apt update && sudo apt upgrade -y

# 7. Install Docker Engine (NOT Docker Desktop)
sudo apt install -y ca-certificates curl gnupg lsb-release

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 8. Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker

# 9. Verify Docker works
docker run hello-world
```

### Phase 2: Project Setup in WSL2

```bash
# ========================
# Inside WSL2 (Ubuntu)
# ========================

# 10. Access Windows files from WSL2
# Windows C:\ drive is at /mnt/c/
# Project files on Windows: /mnt/c/Projects/TenBit/RAG/

# Option A: Work directly from Windows filesystem (easier for Windows users)
cd /mnt/c/Projects/TenBit/RAG

# Option B: Copy to WSL2 native ext4 filesystem (better performance)
cp -r /mnt/c/Projects/TenBit/RAG ~/tenbit-rag
cd ~/tenbit-rag

# 11. Create docker-compose.yml
cat > docker-compose.yml << 'DOCKERCOMPOSE'
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
    restart: unless-stopped
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
    restart: unless-stopped
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
          memory: "2G"

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      - rag_network
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
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
    restart: unless-stopped
    networks:
      - rag_network
    volumes:
      - rag_data:/app/.rbs_rag
      - ./src/rbs_rag/web/static:/app/src/rbs_rag/web/static
    env_file:
      - .env.production
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
    restart: unless-stopped
    networks:
      - rag_network
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
      - rag_data:/app/.rbs_rag:ro
    depends_on:
      - rag_api
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: "256M"
DOCKERCOMPOSE
```

### Phase 3: Create Dockerfile and Configuration

```dockerfile
# ========================
# Dockerfile
# ========================
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] pydantic pydantic-settings \
        python-multipart sqlite-utils httpx python-json-logger \
        pillow numpy \
        pypdf openpyxl xlrd python-pptx \
        qdrant-client redis \
        asyncpg aiosqlite \
        psycopg2-binary

# Copy application code
COPY src/ src/
COPY .env.production .

EXPOSE 8000

CMD ["uvicorn", "rbs_rag.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]
```

### Phase 4: Environment and Nginx Configuration

```bash
# ========================
# .env.production
# ========================
cat > .env.production << 'EOF'
POSTGRES_PASSWORD=generate-a-strong-password-here
REDIS_PASSWORD=another-strong-password-here

# Database
RAG_ENV=production
RAG_DB_URL=postgresql+asyncpg://rag_user:${POSTGRES_PASSWORD}@postgres:5432/rag

# Qdrant
RAG_QDRANT_HOST=qdrant
RAG_QDRANT_PORT=6333
RAG_QDRANT_HTTPS=false

# Redis
RAG_REDIS_HOST=redis
RAG_REDIS_PORT=6379
RAG_REDIS_PASSWORD=${REDIS_PASSWORD}

# LLM
RAG_LLM_API_KEY=your-gemini-api-key-here
RAG_LLM_PROVIDER=gemini
RAG_LLM_MODEL=gemini-2.5-flash-lite
EOF
```

```nginx
# ========================
# nginx.conf
# ========================
# Rate limit zones
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=chat:10m rate=10r/s;

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name rag.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name rag.yourdomain.com;

    # SSL (Let's Encrypt)
    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # File upload size (adjust as needed)
    client_max_body_size 100M;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    gzip_min_length 1000;

    # API endpoints (proxied to FastAPI)
    location /api/ {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 120s;
        limit_req zone=api burst=20 nodelay;
    }

    # Chat endpoints (lower rate limit)
    location /api/v1/chat {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
        limit_req zone=chat burst=10 nodelay;
    }

    # SSE streaming (no buffering)
    location /api/v1/chat/stream {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # SSE streaming (external integration)
    location /api/v1/chat/streaming {
        proxy_pass http://rag_api:8000/api/v1/chat/stream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # Widget
    location /widget {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend (static HTML dashboard)
    location / {
        proxy_pass http://rag_api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Phase 5: SSL Certificate Setup

```bash
# ========================
# On your domain's DNS provider:
# Add A record: rag → YOUR_PUBLIC_IP
# Or CNAME: rag → YOUR_DYNAMIC_DNS_HOSTNAME
# ========================

# Create SSL directory
mkdir -p ssl

# Use acme.sh to get Let's Encrypt certificate
docker run -it --rm \
  -v $(pwd)/ssl:/acme.sh \
  -p 80:80 \
  neilpang/acme.sh \
  --issue --standalone -d rag.yourdomain.com \
  --key-file /acme.sh/privkey.pem \
  --fullchain-file /acme.sh/fullchain.pem

# Auto-renewal (add to crontab on WSL2)
# 0 3 * * * docker run --rm -v $(pwd)/ssl:/acme.sh neilpang/acme.sh --cron
```

### Phase 6: Windows Port Forwarding

```powershell
# ========================
# Run on Windows (Admin PowerShell)
# ========================

# Forward ports from Windows to WSL2

# 1. Find WSL2 IP address
wsl hostname -I
# Returns: 172.x.x.x

# 2. Add port forwarding (HTTP + HTTPS)
netsh interface portproxy add v4tov4 \
  listenport=80 listenaddress=0.0.0.0 \
  connectport=80 connectaddress=172.x.x.x

netsh interface portproxy add v4tov4 \
  listenport=443 listenaddress=0.0.0.0 \
  connectport=443 connectaddress=172.x.x.x

# 3. Allow inbound firewall rules
New-NetFirewallRule -DisplayName "WSL2-HTTP-80" -Direction Inbound \
  -LocalPort 80 -Protocol TCP -Action Allow

New-NetFirewallRule -DisplayName "WSL2-HTTPS-443" -Direction Inbound \
  -LocalPort 443 -Protocol TCP -Action Allow

# 4. Verify port proxies
netsh interface portproxy show all

# 5. Create startup script for WSL port forwarding
# (WSL2 IP changes on reboot — this fixes it)
```

**Auto-fix for WSL2 IP Changes (Run on Windows Startup):**

```powershell
# Save as: C:\Scripts\wsl-port-forward.ps1
# Run at Windows startup via Task Scheduler

$wsl_ip = (wsl hostname -I).Trim()
if ($wsl_ip) {
    # Remove old rules
    netsh interface portproxy delete v4tov4 listenport=80
    netsh interface portproxy delete v4tov4 listenport=443

    # Add new rules
    netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=$wsl_ip
    netsh interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=$wsl_ip
}
```

### Phase 7: Docker Compose Deployment

```bash
# ========================
# Inside WSL2 — Project Directory
# ========================

# 1. NetX: Configure your router to forward ports 80 and 443 to your Windows VM
#    (This is specific to your router brand — look for "Port Forwarding" or "NAT" settings)

# 2. Ensure your domain A record points to your public IP
#    (If you don't have a static IP, set up DDNS — most routers support it)

# 3. Build and start all services
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d

# 4. Verify all services are running
docker compose ps

# 5. Check logs
docker compose logs rag_api
docker compose logs nginx

# 6. Test locally (from Windows browser)
curl http://localhost/health
curl https://localhost/health -k

# 7. Test from internet
curl https://rag.yourdomain.com/health
```

### Phase 8: Docker Compose Management Shortcuts

```bash
# ========================
# Useful Docker Commands
# ========================

# View all running containers
docker compose ps

# View logs for a specific service
docker compose logs -f rag_api

# Restart a single service
docker compose restart rag_api

# Stop everything
docker compose down

# Stop and delete volumes (⚠️ deletes all data)
docker compose down -v

# Update a service (pull latest image)
docker compose pull rag_api
docker compose up -d rag_api

# View resource usage
docker stats

# Backup a volume
docker run --rm -v rag_data:/data -v $(pwd):/backup alpine tar -czf /backup/rag_data_$(date +%Y%m%d).tar.gz -C /data .
```

---

## 7. External API Integration (For Clients)

### 7.1 How Integrations Work

The system already has dedicated endpoints for external client integrations:

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /api/v1/chat` | `X-API-Key` header | Chat with RAG, get answer + citations |
| `POST /api/v1/chat/stream` | `X-API-Key` header | SSE streaming chat |
| `POST /api/v1/tenants/{id}/chat` | `X-API-Key` header | Tenant-specific chat |
| `GET /api/v1/tenants/{id}/documents` | `X-API-Key` header | List documents for a tenant |
| `POST /api/v1/tenants/{id}/documents` | `X-API-Key` header | Upload documents |
| `POST /api/v1/tenants/{id}/ingest` | `X-API-Key` header | Trigger ingestion |

### 7.2 Integration Flow for External Clients

```mermaid
sequenceDiagram
    participant Client as Partner Application
    participant DNS as rag.yourdomain.com
    participant API as RAG API
    participant Admin as Admin Panel

    Note over Admin: You create a tenant for the client
    Admin->>API: POST /api/v1/tenants
    Admin->>Admin: Gets tenant_id + api_key
    Admin->>Client: Provide: api_key, endpoint URL

    Note over Client: Client stores api_key securely
    Client->>Client: Upload documents (their own integration)

    Note over Client: Client queries
    Client->>DNS: POST /api/v1/chat
    Note right of Client: Headers:<br/>X-API-Key: sk_given_to_client<br/>Content-Type: application/json<br/><br/>Body:<br/>{"query": "What...?"}

    DNS->>API: Forward request
    API->>API: Validate API key → find tenant
    API->>API: Process query against tenant's documents
    API-->>Client: {<br/>  "answer": "...",<br/>  "citations": [...],<br/>  "validation": {<br/>    "sufficient": true,<br/>    "confidence": 0.87<br/>  }<br/>}
```

### 7.3 Client Onboarding Steps

```bash
# Step 1: Create a tenant for the client (Admin)
curl -X POST https://rag.yourdomain.com/api/v1/tenants \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_MASTER_API_KEY" \
  -d '{
    "tenant_id": "acme-corp",
    "name": "Acme Corporation",
    "llm_provider": "gemini",
    "llm_api_key": "client-specific-llm-key-or-use-yours"
  }'

# Response includes the tenant's API key:
# {
#   "tenant_id": "acme-corp",
#   "api_key": "rbs_rag_sk_a1b2c3d4e5f6..."
# }

# Step 2: Give the client these integration details:
: '
  Integration URL:   https://rag.yourdomain.com/api/v1/chat
  Authentication:    Header: X-API-Key: rbs_rag_sk_a1b2c3d4e5f6...
  Method:            POST
  Content-Type:      application/json

  Request Body:
  {
    "query": "What documents do I have about tax regulations?",
    "session_id": null,        // Optional: for conversation context
    "user_id": null,           // Optional: for user-specific memory
    "filters": null            // Optional: filter by metadata
  }

  Response Body:
  {
    "answer": "Based on your documents...",
    "citations": [
      {
        "index": 0,
        "document_name": "tax-guide-2024.pdf",
        "section": "Section 3.1",
        "chunk_id": "chunk_abc123"
      }
    ],
    "validation": {
      "sufficient": true,
      "confidence": 0.92
    }
  }
'
```

### 7.4 Integration Code Examples for Clients

**Python Client:**
```python
import requests

API_URL = "https://rag.yourdomain.com/api/v1/chat"
API_KEY = "rbs_rag_sk_a1b2c3d4e5f6..."

response = requests.post(
    API_URL,
    headers={
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    },
    json={
        "query": "What is the process for submitting VAT returns?",
    },
)

data = response.json()
print(f"Answer: {data['answer']}")
print(f"Sources: {[c['document_name'] for c in data['citations']]}")
```

**JavaScript Client (Browser):**
```javascript
const API_URL = 'https://rag.yourdomain.com/api/v1/chat';
const API_KEY = 'rbs_rag_sk_a1b2c3d4e5f6...';

async function askRAG(query) {
    const response = await fetch(API_URL, {
        method: 'POST',
        headers: {
            'X-API-Key': API_KEY,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
    });
    return await response.json();
}

// Usage
askRAG('What contracts are expiring this month?')
    .then(data => console.log(data.answer));
```

**JavaScript Client (SSE Streaming):**
```javascript
const eventSource = new EventSource(
  'https://rag.yourdomain.com/api/v1/chat/stream',
  {
    method: 'POST',
    headers: {
      'X-API-Key': 'rbs_rag_sk_a1b2c3d4e5f6...',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query: 'Tell me about my documents' }),
  }
);

// Cannot use EventSource with POST — use fetch + ReadableStream instead

async function streamChat(query) {
    const response = await fetch('https://rag.yourdomain.com/api/v1/chat/stream', {
        method: 'POST',
        headers: {
            'X-API-Key': 'rbs_rag_sk_a1b2c3d4e5f6...',
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = JSON.parse(line.slice(6));
                console.log(data.text);  // Append to chat UI
                if (data.done) {
                    console.log('Stream complete');
                    console.log('Citations:', data.citations);
                }
            }
        }
    }
}
```

### 7.5 Embeddable Widget

The system includes `widget.html` which can be embedded in any website via iframe:

```html
<!-- Add this to any website to embed the RAG chatbot -->
<iframe
  src="https://rag.yourdomain.com/widget?tenant_id=acme-corp"
  width="400"
  height="600"
  style="border: none; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);"
  title="RAG Assistant">
</iframe>
```

### 7.6 Rate Limiting for Integrations

| Endpoint | Default Rate Limit | Configured In |
|----------|-------------------|---------------|
| `/api/v1/chat` | 10 requests/min per API key | Nginx (chat zone) |
| `/api/v1/chat/stream` | 5 concurrent streams per IP | Nginx (chat zone) |
| All other API | 60 requests/min per IP | App-level (Python) |

To adjust per-client limits, modify the Nginx config:

```nginx
# Per-client rate limit (by API key header)
limit_req_zone $http_x_api_key zone=per_client:10m rate=10r/m;

location /api/v1/chat {
    limit_req zone=per_client burst=5 nodelay;
    # ... rest of config
}
```

---

## 8. Windows-Specific Considerations

### 8.1 Auto-Start on Boot

```powershell
# ========================
# Windows Side
# ========================

# 1. Create a startup script
@"
@echo off
wsl -d Ubuntu-22.04 -u root bash -c "cd /home/your-user/tenbit-rag && docker compose --env-file .env.production up -d"
"@ | Out-File -FilePath "C:\Scripts\start-rag.bat" -Encoding ascii

# 2. Add to Windows Task Scheduler:
#    - Trigger: At startup
#    - Action: Start C:\Scripts\start-rag.bat
#    - Run whether user is logged on or not
#    - Run with highest privileges

# 3. Also ensure WSL port forwarding runs at startup
#    Add C:\Scripts\wsl-port-forward.ps1 to Task Scheduler
#    Trigger: At startup
#    Action: powershell.exe -File C:\Scripts\wsl-port-forward.ps1
```

### 8.2 Windows Firewall

```powershell
# Allow inbound traffic to WSL2 ports
New-NetFirewallRule -DisplayName "WSL-RAG-HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "WSL-RAG-HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
```

### 8.3 Backup Strategy

```powershell
# ========================
# Windows Backup Script
# Save as: C:\Scripts\backup-rag.ps1
# Schedule: Daily via Task Scheduler
# ========================

$date = Get-Date -Format "yyyyMMdd"
$backupDir = "D:\RAG-Backups\$date"
$retentionDays = 30

New-Item -ItemType Directory -Path $backupDir -Force

# 1. Backup PostgreSQL (from WSL2)
wsl -d Ubuntu-22.04 bash -c @"
cd ~/tenbit-rag
docker compose exec -T postgres pg_dump -U rag_user rag > /tmp/rag_pg_$date.sql
docker cp rag_api_1:/app/.rbs_rag /tmp/rbs_rag_data_$date
tar -czf /tmp/rag_backup_$date.tar.gz -C /tmp rag_pg_$date.sql rbs_rag_data_$date
"@

# 2. Copy backup from WSL2 to Windows
wsl -d Ubuntu-22.04 bash -c "cp /tmp/rag_backup_$date.tar.gz /mnt/d/RAG-Backups/$date/"

# 3. Backup to external drive
Copy-Item -Path "$backupDir\*" -Destination "E:\RAG-Backups\" -Recurse -Force

# 4. Cleanup old backups (older than 30 days)
Get-ChildItem -Path "D:\RAG-Backups" -Directory |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-$retentionDays) } |
    Remove-Item -Recurse -Force

Write-Output "Backup completed: $date"
```

### 8.4 Monitoring (Windows Native)

- **Windows Task Manager** — view CPU/RAM usage per container
- **Docker Desktop alternative:** Use `docker stats` from WSL2
- **Windows Event Viewer** — for system-level errors
- **Uptime monitoring:** Use UptimeRobot (free) — pings your domain every 5 minutes
- **Disk space:** Windows Storage Sense automatically cleans temp files

### 8.5 Windows Updates

Windows Update will restart your VM. To handle this gracefully:

```powershell
# Set active hours so updates don't restart during business hours
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings" -Name "ActiveHoursStart" -Value 8
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings" -Name "ActiveHoursEnd" -Value 22

# Or use a reboot script that restarts Docker automatically
# (Already handled by the startup script in Task Scheduler)
```

---

## 9. Security Considerations

### 9.1 Network Security

| Layer | Measure | Implementation |
|-------|---------|----------------|
| **Router** | Port forwarding only 443 (HTTPS) | Block all other inbound ports |
| **Router** | DDoS protection | Enable if available on your router |
| **Windows** | Firewall | Only allow 80/443 from LAN, no RDP from WAN |
| **Windows** | Windows Defender | Enable real-time protection |
| **WSL2** | No public ports | Docker containers listen only on internal bridge |
| **Nginx** | SSL + security headers | Configured in nginx.conf |
| **Application** | API key auth | Every endpoint requires valid X-API-Key |
| **Application** | Rate limiting | 60 req/min per IP (app), 10 req/min per client (Nginx) |

### 9.2 Checklist

- [ ] Router firewall blocks all ports except 443 (and 80 for SSL redirect)
- [ ] RDP (3389) is NOT exposed to the internet
- [ ] Windows VM has a strong admin password
- [ ] Windows automatic updates enabled
- [ ] SSL certificate valid and auto-renewing
- [ ] PostgreSQL password is strong (generated, not dictionary)
- [ ] Redis password is set
- [ ] API keys are UUIDs (system auto-generates them)
- [ ] Docker containers run as non-root where possible
- [ ] Backups are encrypted if stored offsite

---

## 10. Production Readiness Checklist

- [ ] WSL2 + Ubuntu 22.04 installed and configured
- [ ] Docker Engine installed (inside WSL2 — not Docker Desktop)
- [ ] RAM limit set in `.wslconfig` (recommended: 8 GB)
- [ ] `docker-compose.yml` created with all services
- [ ] `.env.production` created with all secrets
- [ ] Dockerfile builds successfully
- [ ] `docker compose up -d` starts all services
- [ ] Health endpoint returns 200: `curl https://localhost/health`
- [ ] Dashboard loads: `https://rag.yourdomain.com`
- [ ] API docs load: `https://rag.yourdomain.com/docs`
- [ ] SSL certificate obtained and auto-renewing
- [ ] Windows port forwarding configured (80/443 → WSL2)
- [ ] Windows firewall allows inbound 80/443
- [ ] Router port forwarding configured (WAN 443 → VM IP)
- [ ] Domain A record points to public IP (or DDNS configured)
- [ ] Startup script configured in Task Scheduler
- [ ] Backup script written and tested
- [ ] Create a test tenant and verify external API integration
- [ ] Load test: simulate 10 concurrent queries
- [ ] Confirm CORS is open (already configured as `*`)
- [ ] Client integration documented and ready to share

---

## 11. Comparison: On-Premises vs. Other Options

| Criterion | Your Windows VM | Cloud VPS (€5–25/mo) | Managed PaaS |
|-----------|----------------|---------------------|--------------|
| **Monthly Cost** | **€0–15** | €5–50 | €5–200 |
| **Setup Time** | 1–2 days | 2–4 hours | 1–2 hours |
| **Hardware Control** | ✅ Full | ❌ Shared | ❌ None |
| **Upgradability** | ✅ Add RAM/disk anytime | ✅ Click to upgrade | ❌ Plan limits |
| **Uptime Dependence** | Your internet + power | Provider SLA (99.9%) | Provider SLA (99.95%) |
| **Public IP** | ISP-dependent (may need DDNS) | ✅ Static IP provided | ✅ Custom domain |
| **Security** | Your responsibility | Shared responsibility | Provider handles infra |
| **API Integration** | ✅ Same API | ✅ Same API | ✅ Same API |
| **Data Sovereignty** | ✅ 100% on your hardware | ⚠️ On provider servers | ⚠️ On provider servers |

> **Verdict:** Your on-premises Windows VM is **excellent for production** — you get cloud-equivalent specs at a fraction of the cost. The only downsides are (1) you need a static public IP or DDNS, and (2) you're responsible for uptime (power, internet, hardware). For a business-critical system, pair this with a cheap €4 Hetzner VPS as a hot standby (see Doc 6 — MVP).
