# Minimum Viable Production (MVP) Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Get the TenBit RAG Platform into production at the lowest possible cost while maintaining reliability, security, and a professional setup. This is the fastest path to a live system for evaluation, demo, or small-scale use.

**The MVP Stack:**
- **1 tiny VPS** — Hetzner CX22 (2 vCPU, 4 GB RAM, 40 GB SSD) at ~€4/mo
- **SQLite** — no PostgreSQL migration needed (the current database)
- **No Qdrant** — use SQLite vector search (working, just less performant at scale)
- **No Redis** — in-memory session storage is sufficient for small deployments
- **Cloudflare Tunnel** — free, no public IP needed, auto SSL
- **Everything in one systemd service** — simple, debuggable, monitorable

**Target Capacity:**
- Up to 10 tenants
- Up to 500 documents per tenant
- Up to 50 queries per day
- Response time: ~3–8 seconds per query

**Timeline:** 4–6 hours (same-day deployment)

**Team Requirements:** 1 Developer (you)

**Total Monthly Cost: ~€4** (just the VPS)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Cloudflare Edge                         │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │  DNS: rag.domain  │    │  Cloudflare Tunnel           │   │
│  │  → CNAME to tunnel│    │  (cloudflared, auto-SSL)     │   │
│  └──────────────────┘    └──────────────┬───────────────┘   │
│                                          │                   │
└──────────────────────────────────────────┼───────────────────┘
                                           │
                           No public ports │ (tunnel outbound)
                                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 VPS — Hetzner CX22 (€4/mo)                    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Uvicorn (systemd: rag-api)                           │   │
│  │  ──────────────────────────                           │   │
│  │  - FastAPI app on port 8000                           │   │
│  │  - 2 workers (uvicorn --workers 2)                    │   │
│  │  - Gunicorn as process manager                        │   │
│  │                                                       │   │
│  │  SQLite: /opt/tenbit-rag/data/rag.db                  │   │
│  │  Config: /opt/tenbit-rag/.rbs_rag/config.json         │   │
│  │  Uploads: /opt/tenbit-rag/data/documents/             │   │
│  │                                                       │   │
│  │  No PostgreSQL, No Qdrant, No Redis                   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│   Data: /opt/tenbit-rag/data/                                │
│   Logs: /var/log/tenbit-rag/                                 │
│   Backup: /backups/tenbit-rag/                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Resource Requirements

### Total System Resource Usage

| Process       | vCPU    | RAM    | Disk    | Notes                    |
|---------------|---------|--------|---------|--------------------------|
| RAG API (2 workers) | 1 CPU | 1.0 GB | 200 MB | Python + deps           |
| SQLite        | 0.1 CPU | 32 MB  | 1–10 GB | Embedded in Python      |
| Cloudflare Tunnel | 0.1 CPU | 64 MB | 50 MB | cloudflared binary      |
| System (OS)   | 0.5 CPU | 512 MB | 10 GB  | Ubuntu 22.04 LTS        |
| **Total Used** | **1.7** | **1.6 GB** | **~20 GB** |                     |
| **Available**  | **2**   | **4 GB**  | **40 GB**  | Hetzner CX22           |
| **Headroom**   | **15%** | **60%** | **50%** | Room to grow           |

### Capacity Limits

| Metric                | Limit                    | Bottleneck              |
|-----------------------|--------------------------|-------------------------|
| Max documents         | 5,000 total              | SQLite write throughput |
| Max tenants           | 10                       | SQLite concurrent reads |
| Max chunks            | 50,000                   | RAM for embeddings      |
| Max queries/minute    | 10                       | Single-threaded SQLite  |
| Max file upload       | 50 MB                    | Uvicorn body limit      |
| Daily active users    | ~20                      | Worker count            |

---

## 4. Cost Comparison

### MVP Monthly Cost Breakdown

| Component       | Provider     | Plan           | Monthly     | Notes                 |
|----------------|--------------|----------------|------------|-----------------------|
| **VPS**        | Hetzner      | CX22           | **€3.99**  | Best value globally   |
| **Domain**     | Cloudflare   | Free           | $0         | Or existing domain    |
| **Tunnel**     | Cloudflare   | Free           | $0         | No egress fees        |
| **SSL**        | Cloudflare   | Universal SSL  | $0         | Auto-provisioned      |
| **DDoS**       | Cloudflare   | Free           | $0         | Included              |
| **LLM API**    | Gemini       | Pay-per-use    | ~$5–20**   | Depends on usage      |
| **Monitoring** | Netdata      | Free           | $0         | 1-line install        |
| **Backups**    | Backblaze B2 | 10 GB free     | $0         | Or S3-compatible      |
| **Total**      |              |                | **~€4 + LLM cost** |                 |

### Alternative VPS Providers

| Provider      | Plan         | vCPU | RAM  | Storage | Monthly Cost | Notes                 |
|---------------|--------------|------|------|---------|-------------|-----------------------|
| **Hetzner**   | CX22         | 2    | 4 GB | 40 GB   | **€3.99**   | ⭐ Best pick           |
| **BuyVM**     | Slice 1024   | 1    | 1 GB | 256 GB  | **$3.50**   | Lots of storage       |
| **LowEndBox** | Various      | 1    | 1 GB | 20 GB   | **$2–3**    | Random deals          |
| **Oracle Cloud** | Free Tier | 4   | 24 GB| 200 GB  | **$0**      | Requires signup, limited availability |
| **Hostinger** | VPS 1        | 1    | 3 GB | 80 GB   | **$9**      | More expensive        |

> Note: SQLite has no additional licensing cost. The entire application stack is open-source.

---

## 5. Step-by-Step Implementation

### 5.1 Deploy in Under 1 Hour

```bash
# ============================================
# STEP 1: Provision VPS — 10 minutes
# ============================================
# 1. Go to hetzner.com → Cloud → Create a project
# 2. Create a CX22 instance (Ubuntu 22.04, Frankfurt region)
# 3. Add your SSH key
# 4. Note the IP address
# 5. SSH in: ssh root@<VPS_IP>

# ============================================
# STEP 2: Basic Server Setup — 10 minutes
# ============================================
apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3-pip curl git ufw

# Create application user
useradd -m -s /bin/bash rag
usermod -aG sudo rag
echo "rag ALL=(ALL) NOPASSWD:/bin/systemctl" >> /etc/sudoers.d/rag

# Setup directories
mkdir -p /opt/tenbit-rag/{src,data,logs}
chown -R rag:rag /opt/tenbit-rag

# Firewall (even though tunnel removes need, belt-and-suspenders)
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# ============================================
# STEP 3: Deploy the Application — 15 minutes
# ============================================
su - rag
git clone https://github.com/your-org/tenbit-rag.git /opt/tenbit-rag/src
cd /opt/tenbit-rag/src

# Create virtual environment
python3.11 -m venv ../venv
source ../venv/bin/activate

# Install (with all extras for document parsing)
pip install --upgrade pip
pip install -e .[all]

# ============================================
# STEP 4: Configure — 5 minutes
# ============================================
mkdir -p /opt/tenbit-rag/.rbs_rag

cat > /opt/tenbit-rag/.rbs_rag/config.json << 'CONFIGEOF'
{
  "tenant_id": "production",
  "storage": {
    "provider": "sqlite",
    "path": "/opt/tenbit-rag/data/rag.db"
  },
  "llm": {
    "provider": "gemini",
    "api_key": "YOUR_GEMINI_API_KEY",
    "model": "gemini-2.5-flash-lite"
  },
  "observability": {
    "structured_logging": true,
    "log_level": "INFO"
  }
}
CONFIGEOF

# Create startup script
cat > /opt/tenbit-rag/start.sh << 'SCRIPT'
#!/bin/bash
source /opt/tenbit-rag/venv/bin/activate
cd /opt/tenbit-rag/src
exec uvicorn rbs_rag.web.server:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 2 \
  --log-level info
SCRIPT

chmod +x /opt/tenbit-rag/start.sh
chown -R rag:rag /opt/tenbit-rag

# ============================================
# STEP 5: Systemd Service — 5 minutes
# ============================================
cat > /etc/systemd/system/rag-api.service << 'UNIT'
[Unit]
Description=TenBit RAG API (MVP)
After=network.target

[Service]
Type=simple
User=rag
Group=rag
WorkingDirectory=/opt/tenbit-rag/src
ExecStart=/opt/tenbit-rag/start.sh
Restart=always
RestartSec=5
StandardOutput=append:/var/log/tenbit-rag/stdout.log
StandardError=append:/var/log/tenbit-rag/stderr.log
LimitNOFILE=65536
Environment=RAG_ENV=production

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now rag-api

# Verify
systemctl status rag-api
curl http://127.0.0.1:8000/health

# ============================================
# STEP 6: Cloudflare Tunnel — 10 minutes
# ============================================
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
dpkg -i /tmp/cloudflared.deb

cloudflared tunnel login  # Opens a browser to authenticate

cloudflared tunnel create tenbit-rag-mvp

cloudflared tunnel route dns tenbit-rag-mvp rag.yourdomain.com

mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yaml << 'TUNNEL'
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /root/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: rag.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
TUNNEL

cloudflared service install

# ============================================
# DONE! Your RAG system is live!
# ============================================
# Open: https://rag.yourdomain.com
# API:  https://rag.yourdomain.com/api/v1
# Docs: https://rag.yourdomain.com/docs
```

### 5.2 Verify Production Readiness

```bash
# 1. Health check
curl https://rag.yourdomain.com/health
# Expected: {"status":"ok","version":"1.0.0","uptime":"X seconds"}

# 2. Tenant creation
curl -X POST https://rag.yourdomain.com/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"mvp-test","name":"MVP Test","llm_provider":"gemini","llm_api_key":"your-key"}'
# Expected: 201 Created

# 3. Upload a document
curl -X POST https://rag.yourdomain.com/api/v1/tenants/mvp-test/documents \
  -F "file=@test-document.pdf"
# Expected: {"document_id":"abc123","status":"queued"}

# 4. Trigger ingestion
curl -X POST https://rag.yourdomain.com/api/v1/tenants/mvp-test/ingest
# Expected: {"status":"started"}

# 5. Query
curl -X POST https://rag.yourdomain.com/api/v1/tenants/mvp-test/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"What is in my documents?"}'
# Expected: {"response":"...","sources":[...]}
```

---

## 6. Security & Backup

### Security Checklist (MVP)

```
✅ No public ports — Cloudflare Tunnel only (outbound connections)
✅ SSL/TLS — Cloudflare Universal SSL (automatic)
✅ DDoS protection — Cloudflare Free plan
✅ SSH key-only — password auth disabled
✅ Firewall — UFW allowing only SSH
✅ Auto-updates — unattended-upgrades installed
✅ LLM API key — stored in config, not in code
✅ Rate limiting — app-level, 60 req/min default
```

### Backup Strategy (Free)

```bash
#!/bin/bash
# /usr/local/bin/backup-mvp.sh
# Run: crontab -e → 0 3 * * * /usr/local/bin/backup-mvp.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/tenbit-rag"
mkdir -p "$BACKUP_DIR"

# 1. Copy SQLite database
cp /opt/tenbit-rag/data/rag.db "$BACKUP_DIR/rag_$DATE.db"

# 2. Copy uploaded documents
tar -czf "$BACKUP_DIR/documents_$DATE.tar.gz" /opt/tenbit-rag/data/documents 2>/dev/null

# 3. Copy config
cp /opt/tenbit-rag/.rbs_rag/config.json "$BACKUP_DIR/config_$DATE.json"

# 4. Optional: upload to Backblaze B2 (free 10 GB)
# b2 upload-file rag-backups "$BACKUP_DIR/rag_$DATE.db" "rag_$DATE.db"
# b2 upload-file rag-backups "$BACKUP_DIR/documents_$DATE.tar.gz" "documents_$DATE.tar.gz"

# 5. Cleanup backups older than 14 days
find "$BACKUP_DIR" -name "rag_*.db" -mtime +14 -delete
find "$BACKUP_DIR" -name "documents_*.tar.gz" -mtime +14 -delete

# 6. Email/Slack notification (optional)
# curl -X POST -H "Content-Type: application/json" \
#   -d '{"text":"RAG MVP backup completed: '$DATE'"}' \
#   $SLACK_WEBHOOK_URL
```

**Restore Procedure:**

```bash
# Full restore:
# 1. Provision new Hetzner CX22
# 2. Install dependencies (Steps 2–3 above)
# 3. Stop the service: systemctl stop rag-api
# 4. Restore: cp /backups/rag_20260706.db /opt/tenbit-rag/data/rag.db
# 5. Restart: systemctl start rag-api
# 6. Install Cloudflare Tunnel (Step 6 above)
# Total restore time: ~20 minutes
```

### Monitoring (Free)

```bash
# Netdata — one-line install, beautiful dashboard
bash <(curl -Ss https://my-netdata.io/kickstart.sh)

# Access at: https://rag.yourdomain.com/netdata/
# Or via tunnel: cloudflared tunnel route dns tenbit-rag-mvp netdata.rag.yourdomain.com

# What Netdata monitors automatically:
# ✅ CPU, RAM, disk usage per process
# ✅ Network traffic per interface
# ✅ SQLite query performance
# ✅ Systemd service status
# ✅ Disk I/O and latency
# ✅ Alert thresholds (configure via dashboard)
```

---

## 7. Production Readiness Checklist

- [ ] Hetzner CX22 VPS provisioned and secured
- [ ] Python 3.11 installed with virtual environment
- [ ] Application deployed from Git
- [ ] SQLite database initialized
- [ ] LLM API key configured (Gemini/OpenAI)
- [ ] Admin tenant created with API key
- [ ] Test document uploaded and ingested
- [ ] Test query returns a valid response
- [ ] Cloudflare Tunnel installed and running
- [ ] Domain DNS points to tunnel (CNAME)
- [ ] SSL certificate active (Cloudflare Universal SSL)
- [ ] Health endpoint: https://rag.yourdomain.com/health → 200 OK
- [ ] OpenAPI docs: https://rag.yourdomain.com/docs → Swagger UI
- [ ] Systemd service configured with auto-restart
- [ ] Logging: stdout + stderr log files rotating
- [ ] Backup script written and tested
- [ ] Netdata monitoring installed
- [ ] Unattended-upgrades configured
- [ ] Rollback procedure documented

---

## Appendix: Migration Paths from MVP

When the MVP grows beyond its limits, upgrade along any of these paths:

| Upgrade                | Cost Impact | Complexity | When to Upgrade            |
|------------------------|-------------|------------|----------------------------|
| Add Cloudflare R2      | $0          | Low        | When documents > 1 GB      |
| SQLite → PostgreSQL    | $0–19/mo    | Medium     | When queries > 20/day      |
| Add Qdrant             | $25/mo      | Medium     | When chunks > 10,000       |
| Add Redis              | $0–5/mo     | Low        | When sessions > 100        |
| Bigger VPS             | +€5–20/mo   | Low        | When RAM > 3 GB            |
| Switch to Docker       | $0          | Medium     | When adding services       |
| Add 2nd VPS (HA)       | +€4/mo      | High       | When downtime is critical  |

**Each migration is independent** — you can add PostgreSQL without Docker, or Qdrant without Redis. The MVP architecture is designed to be incrementally upgraded without ever doing a full rewrite.
