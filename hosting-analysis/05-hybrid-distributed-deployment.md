# Hybrid / Distributed Cloud Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform using a best-of-breed hybrid architecture — self-host only the core API on a cheap VPS while leveraging managed cloud services for databases, vector storage, caching, and CDN. This minimizes operational overhead while maximizing reliability and cost-efficiency.

**Why Hybrid?**
- **No DevOps needed** for databases — the cloud handles backups, scaling, patching
- **Pay-as-you-grow** — start free, scale up as usage increases
- **Global CDN** — static frontend deployed to Cloudflare's edge (200+ locations)
- **Built-in HA** — managed services have 99.95%+ uptime SLAs
- **Cost floor near-zero** — free tiers cover first 1GB+ of each service

**Timeline:** 1–2 days (fastest deployment option overall)

**Team Requirements:** 1 Full-Stack Developer

**Key Risks:**
- Egress costs at scale (API ↔ cloud DB traffic)
- Multiple vendor relationships (billing fragmentation)
- Latency if API region differs from DB region
- No offline capability (requires internet for all services)

---

## 2. Architecture

```
                            ┌──────────────────────┐
                            │  Cloudflare DNS       │
                            │  (Global Anycast)     │
                            └──────┬───────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
            ┌───────▼──────┐     │       ┌───────▼──────┐
            │  Cloudflare   │     │       │  Cloudflare   │
            │  Pages        │     │       │  Tunnel       │
            │  (Frontend)   │     │       │  (No public   │
            │  Free Tier    │     │       │   IP needed)  │
            └──────────────┘     │       └───────┬──────┘
                                 │               │
                          ┌──────▼───────────────▼──────┐
                          │  Tiny VPS (e.g. Hetzner CX22)│
                          │  $4/mo — RAG Core API only   │
                          │  (No databases on this box)  │
                          └──────────────┬──────────────┘
                                         │
           ┌─────────────────────────────┼─────────────────────────────┐
           │                             │                             │
    ┌──────▼──────┐             ┌────────▼───────┐          ┌─────────▼──────────┐
    │  Neon       │             │  Qdrant Cloud   │          │  Upstash Redis     │
    │  PostgreSQL  │             │  Vector DB      │          │  Serverless Cache  │
    │  Free: 0.5GB │             │  Free: 1GB RAM  │          │  Free: 100MB      │
    │  Paid: $19+  │             │  Paid: $25/mo   │          │  Paid: $5/mo      │
    └──────────────┘             └─────────────────┘          └───────────────────┘
```

---

## 3. Resource Requirements

### Per Component

| Component       | Provider      | Plan              | vCPU | RAM     | Storage  | Monthly Cost |
|----------------|---------------|-------------------|------|---------|----------|-------------|
| **Core API**   | Hetzner VPS   | CX22              | 2    | 4 GB    | 40 GB    | **€4**      |
| **PostgreSQL** | Neon (Serverless) | Free Tier     | 0.25 | 1 GB    | 0.5 GB   | **$0**      |
|                |               | Pro (Scale)      | 2    | 4 GB    | 10 GB    | **$19**     |
| **Vector DB**  | Qdrant Cloud  | Free Tier        | —    | 1 GB    | 1 GB     | **$0**      |
|                |               | Pro (Scale)      | —    | 4 GB    | 50 GB    | **$99**     |
| **Cache**      | Upstash Redis | Free Tier        | —    | 100 MB  | —        | **$0**      |
|                |               | Pro              | —    | 1 GB    | —        | **$5**      |
| **CDN/Static** | Cloudflare Pages | Free Tier     | —    | —       | —        | **$0**      |
| **Tunnel**     | Cloudflare Tunnel | Free          | —    | —       | —        | **$0**      |
| **Total (Free)** | | | **2** | **5 GB** | **41 GB** | **~€4** |
| **Total (Prod)** | | | **4** | **9 GB** | **100 GB** | **~$48** |

### Cost Breakdown by Scale

| Scale Level       | Free Tier      | Growth         | Production      | Enterprise      |
|-------------------|---------------|----------------|-----------------|-----------------|
| **Tenants**       | 1             | 5              | 20              | 100             |
| **Documents**     | 500           | 5,000          | 50,000          | 500,000         |
| **Queries/Day**   | 50            | 500            | 5,000           | 50,000          |
| **VPS Cost**      | €4            | €4             | €9              | €20             |
| **Neon PG**       | $0            | $19            | $69             | $299            |
| **Qdrant Cloud**  | $0            | $25            | $99             | $499            |
| **Upstash Redis** | $0            | $5             | $15             | $50             |
| **Cloudflare**    | $0            | $0             | $20 (Workers)   | $200 (Enterprise)|
| **Egress**        | $0            | $2             | $10             | $50             |
| **Total/Month**   | **~€4**       | **~$55**       | **~$222**       | **~$1,119**     |

---

## 4. Cost Comparison

### Full Hybrid Stack Pricing Across Providers

| Service Type   | Best Provider  | Free Tier           | Paid Starts At | Production (50k docs) |
|----------------|---------------|---------------------|---------------|----------------------|
| **PostgreSQL** | **Neon**      | 0.5 GB DB, 10 GB/month | $19         | $69/mo               |
|                 | Supabase      | 0.5 GB DB           | $25           | $95/mo               |
|                 | Aiven         | None (7-day trial)  | $19           | $79/mo               |
| **Vector DB**  | **Qdrant Cloud** | 1 GB RAM           | $25          | $99/mo               |
|                 | Pinecone      | None                | $70           | $700/mo              |
|                 | Weaviate Cloud| 0.5 GB (limited)    | $25           | $150/mo              |
| **Redis Cache**| **Upstash**   | 100 MB, 10k commands/day | $5       | $15/mo               |
|                 | Redis Cloud   | 30 MB               | $7            | $50/mo               |
| **Object Store**| **Backblaze B2** | 10 GB free        | $0.006/GB/mo | $0.60/mo for 100 GB  |
|                 | AWS S3        | 5 GB (1 year)       | $0.023/GB/mo  | $2.30/mo for 100 GB  |
| **CDN/Static** | **Cloudflare Pages** | Unlimited bandwidth | $20 (Workers) | $200 (Enterprise) |
|                 | Vercel        | 100 GB bandwidth    | $20           | $200/mo              |
| **VPS (API)**  | **Hetzner**   | —                   | €4            | €9/mo                |
|                 | Fly.io        | $5 credit/mo        | $2.48         | $20/mo               |

---

## 5. Step-by-Step Implementation

### 5.1 Cloudflare Setup (Static Frontend + Tunnel)

```bash
# 1. Create Cloudflare account and add your domain

# 2. Deploy frontend to Cloudflare Pages
#    - Go to Cloudflare Dashboard → Pages → Create a project
#    - Connect your GitHub repo
#    - Build settings: None (it's static HTML)
#    - Output dir: src/rbs_rag/web/static
#    - Deploy!
#    Result: https://tenbit-rag.pages.dev

# 3. Custom domain: Pages → Custom domains → rag.yourdomain.com
#    Cloudflare automatically provisions SSL

# 4. Install Cloudflare Tunnel (on the VPS)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
dpkg -i /tmp/cloudflared.deb

# 5. Authenticate tunnel
cloudflared tunnel login

# 6. Create tunnel
cloudflared tunnel create tenbit-rag
# This creates a tunnel ID and credentials file

# 7. Route DNS
cloudflared tunnel route dns tenbit-rag api.rag.yourdomain.com

# 8. Create tunnel config
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yaml << 'EOF'
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.rag.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# 9. Install as systemd service
cloudflared service install

# Result: API accessible at https://api.rag.yourdomain.com
# No open ports needed on the VPS!
```

### 5.2 Neon PostgreSQL Setup

```bash
# 1. Sign up at neon.tech
# 2. Create a project (choose region close to your VPS)

# 3. Get connection string from Neon Dashboard
#    postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb

# 4. Set as environment variable on the VPS
echo 'export DATABASE_URL="postgresql+asyncpg://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb"' >> /etc/environment

# 5. Test connection
psql postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb -c "SELECT 1;"
```

### 5.3 Qdrant Cloud Setup

```bash
# 1. Sign up at cloud.qdrant.io
# 2. Create a cluster (Free tier: 1 GB RAM, 1 GB storage)
#    Choose same region as VPS

# 3. Get the cluster URL and API key from the dashboard
#    URL: https://xxx-xxx.cloud.qdrant.io:6333
#    API Key: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 4. Verify connectivity
curl -s -H "api-key: $QDRANT_API_KEY" https://xxx-xxx.cloud.qdrant.io:6333/health
# Expected: {"status":"ok","title":"qdrant","version":"1.10.0"}
```

### 5.4 Upstash Redis Setup

```bash
# 1. Sign up at upstash.com
# 2. Create a Redis database (Free tier: 100 MB)

# 3. Get REST API URL and token
#    UPSTASH_REDIS_URL: https://xxx.upstash.io
#    UPSTASH_REDIS_TOKEN: xxxxxxxx

# 4. Set environment variables on VPS
export UPSTASH_REDIS_URL="https://xxx.upstash.io"
export UPSTASH_REDIS_TOKEN="xxxxxxxx"

# 5. Quick test
curl -s -X POST "$UPSTASH_REDIS_URL/ping" \
  -H "Authorization: Bearer $UPSTASH_REDIS_TOKEN"
# Expected: {"result":"PONG"}
```

### 5.5 VPS Setup (Core API only)

```bash
# Deploy on cheapest VPS: Hetzner CX22 (~€4/mo, 2 vCPU, 4 GB RAM)

# 1. Install Python and dependencies
apt update && apt install -y python3.11 python3.11-venv nginx

# 2. Deploy RAG API (same as VPS document, steps 5.4–5.5)
# But configure it to use the external services:

cat > /etc/tenbit-rag/config.json << 'EOF'
{
  "tenant_id": "production",
  "storage": {
    "provider": "postgresql",
    "path": "postgresql+asyncpg://user:password@ep-xxx.neon.tech/neondb"
  },
  "qdrant": {
    "host": "xxx-xxx.cloud.qdrant.io",
    "port": 6333,
    "api_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "https": true
  },
  "redis": {
    "provider": "upstash",
    "url": "https://xxx.upstash.io",
    "token": "xxxxxxxx"
  },
  "llm": {
    "provider": "gemini",
    "api_key": "your-key",
    "model": "gemini-2.5-flash-lite"
  }
}
EOF

# 3. Start the API
systemctl start rag-api

# 4. Verify the tunnel
curl https://api.rag.yourdomain.com/health
# Expected: {"status":"ok"}
```

### 5.6 Connecting Frontend to API

In Cloudflare Pages → your frontend project → Settings → Environment Variables:

```
VITE_API_BASE_URL=https://api.rag.yourdomain.com/api/v1
```

This tells the frontend SPA to use the tunneled API endpoint. No CORS issues since Cloudflare handles it.

---

## 6. Security & Backup

### Security Architecture

```
Cloudflare Edge                   VPS (no public ports)
   ┌──────┐                       ┌──────────┐
   │ WAF   │── SSL only ──────▶   │ Tunnel   │──▶ localhost:8000
   │ DDoS  │                       │ (no IP)  │
   │ Bot   │                       └──────────┘
   │ Mgmt  │
   └──────┘
```

- **No public IP needed** — Cloudflare Tunnel means the VPS has no exposed ports
- **WAF rules** — block SQL injection, XSS, bot traffic at the edge
- **API keys** — managed services (Neon, Qdrant, Upstash) restrict by IP
- **Data in transit** — all connections are TLS/SSL

### Backup Strategy

| Data          | Managed By      | Automatic?       | Restore Time     | Cost             |
|---------------|----------------|------------------|------------------|------------------|
| PostgreSQL    | Neon           | Point-in-time    | ~5 minutes       | Included         |
| Vectors       | Qdrant Cloud   | Daily snapshots  | ~10 minutes      | Included         |
| Redis         | Upstash        | AOF persistence  | ~1 minute        | Included         |
| Uploads/Docs  | VPS disk        | rsync to B2      | ~30 minutes      | ~$0.01/GB/mo    |
| Config        | Git            | Versioned        | ~10 minutes      | Free             |

### Disaster Recovery

```bash
# Full recovery script (run on a fresh VPS):
#!/bin/bash
# 1. Install cloudflared and authenticate
# 2. Clone git repo and install deps
# 3. Set environment variables (Neon, Qdrant, Upstash URLs)
# 4. Start rag-api service
# 5. Verify health endpoint

# Total recovery time: ~20 minutes
```

---

## 7. Production Readiness Checklist

- [ ] Cloudflare account created with domain added
- [ ] Frontend deployed to Cloudflare Pages
- [ ] API deployed on VPS behind Cloudflare Tunnel
- [ ] Neon PostgreSQL provisioned and connected
- [ ] Qdrant Cloud cluster provisioned and connected
- [ ] Upstash Redis provisioned and connected
- [ ] LLM API key configured
- [ ] No public ports on VPS (only tunnel)
- [ ] CORS configured for Cloudflare Pages domain
- [ ] File upload limit: 100 MB (configurable)
- [ ] WAF rules: rate limiting, bot management
- [ ] Neon point-in-time recovery confirmed
- [ ] Qdrant snapshot created and verified
- [ ] Load test: 50 concurrent queries via tunnel
- [ ] Monthly cost estimate documented
- [ ] Rollback: point Cloudflare DNS to old VPS

---

## Appendix: Alternative Provider Combinations

### Budget Combo (~$5/mo)
- **VPS:** Hetzner CX22 (€4)
- **PostgreSQL:** Neon Free Tier ($0)
- **Vector DB:** SQLite (embedded, no Qdrant — free)
- **Redis:** Upstash Free Tier ($0)
- **CDN:** Cloudflare Pages Free ($0)

### Balanced Combo (~$50/mo)
- **VPS:** Hetzner CX32 (€13)
- **PostgreSQL:** Neon Pro ($19)
- **Vector DB:** Qdrant Cloud Pro ($25)
- **Redis:** Upstash Pro ($5)
- **CDN:** Cloudflare Pages Free ($0)

### High-Performance Combo (~$200/mo)
- **VPS:** Hetzner CAX41 (€30, ARM-based)
- **PostgreSQL:** Neon Scale ($69)
- **Vector DB:** Qdrant Cloud Business ($99)
- **Redis:** Upstash Pro ($15)
- **CDN:** Cloudflare Workers ($20)
