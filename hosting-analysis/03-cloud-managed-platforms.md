# Cloud Managed Platform Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform on Platform-as-a-Service (PaaS) providers — Railway, Render, and Fly.io — eliminating server management while maintaining production quality.

**Why Managed Platforms?**
- Zero server management — no SSH, no apt, no systemd
- Automatic SSL, auto-scaling, and global CDN
- Built-in PostgreSQL, Redis, and object storage
- Deploy from Git — CI/CD is native
- Pay-per-use pricing (idle = near-zero cost)
- Best for teams with limited DevOps resources

**Timeline:** 1–2 days per platform (significantly faster than VPS)

**Team Requirements:** 1 Full-Stack Developer (part-time evenings)

**Key Risks:**
- No custom Qdrant installation — requires Qdrant Cloud or SQLite fallback
- Vendor lock-in (platform-specific config files)
- Egress bandwidth costs at scale
- Cold starts on free tiers (5–15 seconds)

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   Managed Platform                         │
│                                                           │
│  ┌──────────┐    ┌──────────┐    ┌────────────────────┐   │
│  │  CDN      │───▶│  Web     │───▶│  Managed PostgreSQL│   │
│  │  (Global)  │    │  Service │    │  (Platform-native)  │   │
│  └──────────┘    └────┬─────┘    └────────────────────┘   │
│                       │                                     │
│                ┌──────▼──────┐    ┌────────────────────┐   │
│                │  Redis      │    │  Qdrant Cloud       │   │
│                │  (Managed)  │    │  (External Service) │   │
│                └─────────────┘    └────────────────────┘   │
│                                                           │
│  Deploy via: git push (auto-build + deploy)                │
│  Config: Environment Variables (no .env files)             │
│  Logs: Platform dashboard + stdout                         │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Resource Requirements

### Per Service Allocation

| Component     | Railway          | Render           | Fly.io           |
|---------------|-----------------|------------------|------------------|
| **Web Service** | 1 vCPU / 1 GB | 1 vCPU / 512 MB | 1 vCPU / 256 MB |
| **PostgreSQL**  | 1 vCPU / 1 GB | 1 vCPU / 1 GB   | 1 vCPU / 1 GB   |
| **Redis**       | 256 MB         | 250 MB           | 250 MB          |
| **Qdrant Cloud** | 1 GB RAM     | 1 GB RAM         | 1 GB RAM        |

### Storage Requirements

| Data Type     | Initial  | 6 Months  | 12 Months |
|---------------|----------|-----------|-----------|
| Database      | 1 GB     | 5 GB      | 15 GB     |
| Vectors+Indexes | 500 MB | 2 GB     | 5 GB      |
| Uploads/Docs  | 500 MB   | 3 GB      | 8 GB      |
| **Total**     | **2 GB** | **10 GB** | **28 GB** |

---

## 4. Cost Comparison

### Monthly Pricing by Platform (Starting Tier)

| Component     | Railway                  | Render                    | Fly.io                   |
|---------------|--------------------------|---------------------------|--------------------------|
| **Web**       | $5 (1 vCPU/1 GB)        | $7 (1 vCPU/512 MB)       | $2.48 (shared vCPU/256 MB) |
| **PostgreSQL**| $5 (1 vCPU/1 GB/1 GB)    | $7 (1 vCPU/1 GB)         | $10 (1 GB volume)        |
| **Redis**     | $5 (256 MB)              | $0 (included with web)   | N/A (Upstash)            |
| **Qdrant Cloud** | $25 (1 GB RAM)      | $25 (1 GB RAM)           | $25 (1 GB RAM)           |
| **Egress**    | $0.10/GB after 100 GB   | $0.10/GB after 100 GB    | $0.01/GB (cheap!)        |
| **Total Est.** | **~$40/mo**            | **~$39/mo**              | **~$37/mo**              |

### Production Scale (50+ tenants)

| Provider     | Web (4 vCPU) | PostgreSQL | Redis | Qdrant Cloud | **Total**   |
|--------------|-------------|-----------|-------|-------------|-------------|
| **Railway**  | $50         | $25       | $15   | $99         | **~$189/mo** |
| **Render**   | $58         | $35       | $0    | $99         | **~$192/mo** |
| **Fly.io**   | $34         | $30       | $15*  | $99         | **~$178/mo** |
| **Combined** | **Best mix:** Railway web + Render PG + Fly.io egress + Qdrant = **~$150/mo** |

> *Redis via Upstash on Fly.io. All prices are estimates; actual costs depend on usage.
>
> **Free tiers available:** Railway ($5 credit/mo), Render (static sites free), Fly.io ($5/mo free credit).

---

## 5. Step-by-Step Implementation

### 5.1 Railway Deployment

#### Setup

```bash
# Install Railway CLI
curl -fsSL https://railway.app/install.sh | sh

# Login
railway login

# Initialize in project root
cd tenbit-rag
railway init
```

#### `railway.json`

```json
{
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -e ."
  },
  "deploy": {
    "startCommand": "uvicorn rbs_rag.web.server:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5
  }
}
```

#### `nixpacks.toml`

```toml
[phases.setup]
nixPackages = ["python311", "gcc", "libpq-dev"]

[phases.install]
cmds = ["pip install --upgrade pip", "pip install -e ."]

[start]
cmd = "uvicorn rbs_rag.web.server:app --host 0.0.0.0 --port $PORT"
```

#### Environment Variables (set via Railway Dashboard)

```
RAG_ENV=production
RAG_DB_URL=postgresql+asyncpg://${RAILWAY_POSTGRESQL_USER}:${RAILWAY_POSTGRESQL_PASSWORD}@${RAILWAY_POSTGRESQL_HOST}:${RAILWAY_POSTGRESQL_PORT}/railway
RAG_QDRANT_HOST=your-cluster.cloud.qdrant.io
RAG_QDRANT_PORT=6333
RAG_QDRANT_API_KEY=${QDRANT_API_KEY}
RAG_REDIS_HOST=${RAILWAY_REDIS_HOST}
RAG_REDIS_PORT=6379
RAG_LLM_API_KEY=${LLM_API_KEY}
RAG_LLM_PROVIDER=gemini
```

```bash
# Provision PostgreSQL and Redis
railway add postgresql
railway add redis

# Deploy
railway up
```

#### Optional: Custom Domain

```bash
railway domain rag.yourdomain.com
# Then add CNAME record in DNS provider
```

---

### 5.2 Render Deployment

#### `render.yaml` (Infrastructure as Code)

```yaml
services:
  - type: web
    name: tenbit-rag-api
    env: python
    buildCommand: pip install -e .
    startCommand: uvicorn rbs_rag.web.server:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: RAG_ENV
        value: production
      - key: RAG_DB_URL
        fromDatabase:
          name: tenbit-rag-db
          property: connectionString
      - key: RAG_REDIS_HOST
        fromService:
          name: tenbit-rag-redis
          type: redis
          property: host
      - key: RAG_REDIS_PORT
        fromService:
          name: tenbit-rag-redis
          type: redis
          property: port
      - key: RAG_LLM_API_KEY
        sync: false
      - key: RAG_QDRANT_API_KEY
        sync: false

databases:
  - name: tenbit-rag-db
    databaseName: rag
    user: rag_user
    plan: standard

  - name: tenbit-rag-redis
    plan: free
```

#### Manual Deploy Steps

```bash
# 1. Push to GitHub
git push origin main

# 2. In Render Dashboard:
#    - New Blueprint → connect GitHub repo
#    - Render auto-detects render.yaml
#    - Fill in the missing env vars (RAG_LLM_API_KEY, RAG_QDRANT_API_KEY)
#    - Click "Deploy Blueprint"

# 3. Custom Domain:
#    Settings → Custom Domain → rag.yourdomain.com
#    Add CNAME or ALIAS record in DNS
```

---

### 5.3 Fly.io Deployment

#### `fly.toml`

```toml
app = "tenbit-rag"
primary_region = "fra"

[build]
  builder = "heroku/buildpacks:20"

[env]
  RAG_ENV = "production"
  RAG_LLM_PROVIDER = "gemini"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1
  processes = ["web"]

  [[http_service.checks]]
    path = "/health"
    interval = "15s"
    timeout = "5s"
    method = "GET"

[[services.ports]]
  handlers = ["http"]
  port = 80

[[services.ports]]
  handlers = ["tls", "http"]
  port = 443

[[services.concurrency]]
  type = "connections"
  hard_limit = 250
  soft_limit = 200
```

#### Deployment Commands

```bash
# Install flyctl
curl -fsSL https://fly.io/install.sh | sh

# Login and launch
fly auth login
fly launch --no-deploy

# Set secrets
fly secrets set RAG_LLM_API_KEY=your-key
fly secrets set RAG_QDRANT_API_KEY=your-key
fly secrets set RAG_QDRANT_HOST=your-cluster.cloud.qdrant.io

# Create PostgreSQL
fly postgres create --name tenbit-rag-db
fly postgres attach tenbit-rag-db

# Create volumes for persistence
fly volumes create rag_data --size 5

# Deploy
fly deploy

# Scale
fly scale memory 1024
fly scale count 2  # 2 instances for HA
```

---

### 5.4 SQLite → PostgreSQL Migration (for all platforms)

```bash
# 1. Dump local SQLite
sqlite3 .rbs_rag/rag.db .dump > rag_dump.sql

# 2. Convert syntax (sed replacements for PostgreSQL compatibility)
sed -i 's/AUTOINCREMENT/SERIAL/g' rag_dump.sql
sed -i 's/INTEGER PRIMARY KEY/SERIAL PRIMARY KEY/g' rag_dump.sql
sed -i 's/BLOB/BYTEA/g' rag_dump.sql

# 3. Import to platform PostgreSQL
psql $(railway credentials postgresql) < rag_dump.sql

# 4. Verify
psql $(railway credentials postgresql) -c "SELECT COUNT(*) FROM documents;"
```

---

## 6. Security & Backup

### Platform-Level Security

| Feature          | Railway              | Render               | Fly.io               |
|------------------|---------------------|----------------------|----------------------|
| **SSL**          | Auto (Let's Encrypt)| Auto (Let's Encrypt) | Auto (Let's Encrypt) |
| **WAF**          | No                  | Basic                | No                   |
| **DDoS**         | Cloudflare upstream | Cloudflare upstream  | Cloudflare upstream  |
| **Secrets**      | Encrypted env vars  | Encrypted env vars   | Encrypted secrets    |
| **Network**      | Private networking  | Private networking   | WireGuard tunnel     |
| **Compliance**   | SOC 2               | SOC 2                | SOC 2                |

### Backup Strategy

| Platform   | PostgreSQL                     | Files                    | Vector Index             |
|------------|--------------------------------|--------------------------|--------------------------|
| **Railway** | Auto daily snapshot (7-day)   | No persistent disk      | Qdrant Cloud snapshot    |
| **Render**  | Auto daily snapshot (7-day)   | No persistent disk      | Qdrant Cloud snapshot    |
| **Fly.io**  | `fly postgres backup`         | Volume snapshot         | Qdrant Cloud snapshot    |

### Recommended External Backup

```bash
# Run as a cron job on any machine or GitHub Actions
# Backup script for all three platforms:

python3 -c "
import subprocess, json

# Dump via API
subprocess.run(['curl', '-X', 'GET',
  '-H', f'Authorization: Bearer {API_KEY}',
  f'{PLATFORM_API}/postgres/backup',
  '-o', f'backup_{datetime}.sql.gz'])

# Qdrant snapshot via API
subprocess.run(['curl', '-X', 'POST',
  '-H', f'api-key: {QDRANT_API_KEY}',
  f'https://{QDRANT_CLUSTER}/snapshots'])

# Upload to S3-compatible storage (Backblaze B2 = $0.006/GB/mo)
subprocess.run(['aws', 's3', 'cp', f'backup_{datetime}.sql.gz',
  's3://rag-backups/'])
"
```

---

## 7. Production Readiness Checklist

- [ ] Platform account created with billing configured
- [ ] Application builds and deploys via `git push`
- [ ] Health endpoint responding (`/health`)
- [ ] Managed PostgreSQL provisioned and connected
- [ ] Redis provisioned and connected
- [ ] Qdrant Cloud cluster created and API key configured
- [ ] LLM API key set as environment variable/secret
- [ ] Custom domain configured with SSL
- [ ] File upload limit increased (100 MB minimum)
- [ ] Rate limiting configured (platform or app-level)
- [ ] Logging and metrics reviewed
- [ ] Cold start time measured (acceptable < 10s)
- [ ] Scale test performed (ramp to 50 concurrent users)
- [ ] Rollback procedure documented (previous deploy)
- [ ] Backup tested with restore on staging

---

## Appendix: Platform Comparison Table

| Criteria               | Railway                    | Render                     | Fly.io                      |
|------------------------|----------------------------|----------------------------|-----------------------------|
| **Git Deploy**         | ✅ Yes                     | ✅ Yes                     | ✅ Yes                      |
| **Free Tier**          | $5 credit/mo               | 750 hrs web + PG free      | $5 credit/mo (3 VMs)       |
| **PostgreSQL**         | ✅ Managed                 | ✅ Managed                 | ✅ Managed (separate app)   |
| **Redis**              | ✅ Managed ($5+)           | ✅ Managed (included)      | ❌ Use Upstash              |
| **Persistent Disk**    | ❌ Ephemeral               | ❌ Ephemeral               | ✅ Volumes                  |
| **Auto-scaling**       | ✅ Manual scale            | ✅ Manual scale            | ✅ Auto-scale               |
| **Regions**            | 8 regions                  | 6 regions                  | 30+ regions                 |
| **SSH Access**         | ❌ No                      | ❌ No                      | ✅ `fly ssh`                |
| **Custom Domain**      | ✅ Yes                     | ✅ Yes                     | ✅ Yes                      |
| **Dockerfile Support** | ✅ Yes                     | ✅ Yes                     | ✅ Yes (primary)            |
| **Cold Start (free)**  | ~5s                        | ~10s                       | ~15s                        |
| **Best For**           | Startups, rapid prototyping| Teams wanting simplicity   | Global distribution         |
