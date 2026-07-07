# VPS / Bare-Metal Direct Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform directly on a rented Linux VPS without containerization — services installed natively and managed via systemd.

**Why Direct Deployment?**
- No Docker overhead (~3–5% CPU savings vs containers)
- Simpler debugging (direct process access)
- Lower learning curve for ops teams unfamiliar with Docker
- Direct filesystem access for database tuning
- Slightly lower latency for disk I/O operations

**Timeline:** 3–5 days for initial setup, 1 day/month maintenance

**Team Requirements:** 1 Systems Administrator (part-time)

**Key Risks:**
- Dependency conflicts between Python packages
- Manual process management (no Docker restart policies)
- Inconsistent environment between machines

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────┐
│                    VPS Instance                        │
│                                                        │
│  ┌──────────┐     ┌──────────────────────────────────┐ │
│  │  Nginx    │────▶│  Uvicorn (systemd: rag-api)     │ │
│  │  :443/80  │     │  /opt/tenbit-rag/venv/bin/      │ │
│  └──────────┘     │  uvicorn --workers 4              │ │
│       │           └───┬────────────┬──────────────┬───┘ │
│       │               │            │              │     │
│       │        ┌──────▼──┐  ┌──────▼──┐   ┌──────▼──┐ │
│       │        │ Qdrant   │  │ Redis    │   │PostgreSQL│ │
│       │        │ systemd  │  │ systemd  │   │ systemd  │ │
│       │        └─────────┘  └─────────┘   └──────────┘ │
│       │                                                │
│       └──────────────▶ Static Frontend                  │
│                       (from /opt/tenbit-rag/src/...)    │
│                                                        │
│  All services managed by systemd                        │
│  Data: /var/lib/tenbit-rag/data                         │
│  Config: /etc/tenbit-rag/config.json                    │
│  Logs: /var/log/tenbit-rag/                             │
└──────────────────────────────────────────────────────┘
```

---

## 3. Resource Requirements

### Minimum Viable Stack

| Service     | vCPU | RAM    | Storage | Installation Method          |
|-------------|------|--------|---------|------------------------------|
| RAG API     | 1    | 1 GB   | 500 MB  | Python venv + pip            |
| Qdrant      | 1    | 1 GB   | 5 GB    | Binary or apt package        |
| PostgreSQL  | 1    | 1 GB   | 10 GB   | apt install postgresql-16    |
| Redis       | 0.5  | 256 MB | N/A     | apt install redis            |
| Nginx       | 0.5  | 128 MB | 100 MB  | apt install nginx            |
| **Total**   | **4**| **3.5 GB** | **16 GB** |                          |

### Recommended Production Stack

| Service     | vCPU | RAM    | Storage | Notes                         |
|-------------|------|--------|---------|-------------------------------|
| RAG API     | 2    | 2 GB   | 1 GB    | 4–8 uvicorn workers          |
| Qdrant      | 2    | 4 GB   | 50 GB   | Memory-mapped HNSW indexes   |
| PostgreSQL  | 2    | 2 GB   | 100 GB  | Tuned shared_buffers=512MB   |
| Redis       | 1    | 1 GB   | N/A     | Used for session + rate limit |
| Nginx       | 1    | 256 MB | 100 MB  | Static file serving + proxy  |
| **Total**   | **8**| **9.5 GB** | **151 GB** |                          |

---

## 4. Cost Comparison

### Recommended Stack (8 vCPU, 9.5 GB RAM)

| Provider      | Plan                | vCPU | RAM   | Storage   | Monthly Cost | Transfer  |
|---------------|---------------------|------|-------|-----------|-------------|-----------|
| **Hetzner**   | AX42 (dedicated)    | 4    | 16 GB | 2×480 GB  | **~€32**    | 10 TB     |
| **Hostinger** | VPS Premium 4       | 4    | 8 GB  | 200 GB    | **~$25**    | 8 TB      |
| **DigitalOcean** | Premium 8GB     | 4    | 8 GB  | 160 GB    | **~$48**    | 4 TB      |
| **Linode**    | Dedicated 8GB       | 4    | 8 GB  | 160 GB    | **~$48**    | 4 TB      |
| **OVHcloud**  | Value VPS           | 4    | 8 GB  | 160 GB    | **~$18**    | Unlimited |

### Minimum Stack (4 vCPU, 3.5 GB RAM)

| Provider      | Plan                | vCPU | RAM   | Storage   | Monthly Cost |
|---------------|---------------------|------|-------|-----------|-------------|
| **Hetzner**   | CX22                | 2    | 4 GB  | 40 GB     | **~€4**     |
| **Hostinger** | VPS Premium 2       | 2    | 4 GB  | 100 GB    | **~$12**    |
| **DigitalOcean** | Basic 4GB        | 2    | 4 GB  | 80 GB     | **~$24**    |
| **BuyVM**     | Slice 1024          | 1    | 1 GB  | 256 GB    | **~$3.50**  |

---

## 5. Step-by-Step Implementation

### 5.1 Prerequisites

- Linux VPS with Ubuntu 22.04 LTS or Debian 12
- Root SSH access
- Domain name with DNS A record pointing to VPS IP
- Python 3.11+ (use deadsnakes PPA on Ubuntu)

### 5.2 Initial Server Hardening

```bash
# Update system
apt update && apt upgrade -y
apt install -y curl wget git ufw fail2ban unattended-upgrades

# Create deploy user
useradd -m -s /bin/bash ragadmin
usermod -aG sudo ragadmin
mkdir -p /home/ragadmin/.ssh
chmod 700 /home/ragadmin/.ssh

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# SSH hardening
sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd
```

### 5.3 Install Services

```bash
# PostgreSQL 16
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/postgresql.list
apt update && apt install -y postgresql-16 postgresql-contrib-16

# Create database
sudo -u postgres psql -c "CREATE USER rag_user WITH PASSWORD 'strong-password';"
sudo -u postgres psql -c "CREATE DATABASE rag OWNER rag_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rag TO rag_user;"

# Tune PostgreSQL
cat >> /etc/postgresql/16/main/postgresql.conf << 'EOF'
shared_buffers = 512MB
effective_cache_size = 1.5GB
work_mem = 64MB
maintenance_work_mem = 256MB
random_page_cost = 1.1
effective_io_concurrency = 200
wal_buffers = 16MB
max_connections = 50
EOF
systemctl restart postgresql

# Redis
apt install -y redis-server
sed -i 's/supervised auto/supervised systemd/' /etc/redis/redis.conf
echo "maxmemory 512mb" >> /etc/redis/redis.conf
echo "maxmemory-policy allkeys-lru" >> /etc/redis/redis.conf
systemctl restart redis-server

# Qdrant
curl -sSf https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz | tar xz
mv qdrant /usr/local/bin/
useradd -r -s /bin/false qdrant
mkdir -p /var/lib/qdrant /etc/qdrant

cat > /etc/qdrant/config.yaml << 'EOF'
storage:
  storage_path: /var/lib/qdrant
  performance:
    max_search_threads: 4
service:
  grpc_port: 6334
  http_port: 6333
EOF

# Qdrant systemd service
cat > /etc/systemd/system/qdrant.service << 'EOF'
[Unit]
Description=Qdrant Vector Database
After=network.target

[Service]
Type=simple
User=qdrant
ExecStart=/usr/local/bin/qdrant --config-path /etc/qdrant/config.yaml
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now qdrant

# Nginx
apt install -y nginx certbot python3-certbot-nginx
```

### 5.4 Deploy RAG Application

```bash
# Create application directory
mkdir -p /opt/tenbit-rag/{src,data,logs}
chown -R ragadmin:ragadmin /opt/tenbit-rag

# Clone code (as ragadmin user)
su - ragadmin
git clone https://github.com/your-org/tenbit-rag.git /opt/tenbit-rag/src
cd /opt/tenbit-rag

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e src/[all]

# Create production config
mkdir -p /etc/tenbit-rag
cat > /etc/tenbit-rag/config.json << 'EOF'
{
  "tenant_id": "production",
  "storage": {
    "provider": "postgresql",
    "path": "postgresql+asyncpg://rag_user:password@localhost:5432/rag"
  },
  "qdrant": {
    "host": "localhost",
    "port": 6333,
    "collection_config": {
      "vectors": { "size": 384, "distance": "Cosine" }
    }
  },
  "llm": {
    "provider": "gemini",
    "api_key": "your-api-key",
    "model": "gemini-2.5-flash-lite"
  },
  "observability": {
    "structured_logging": true,
    "log_level": "INFO",
    "log_file": "/var/log/tenbit-rag/api.log"
  }
}
EOF

# Create data symlink
ln -sf /opt/tenbit-rag/data /opt/tenbit-rag/src/.rbs_rag
```

### 5.5 Systemd Service Definition

```ini
[Unit]
Description=TenBit RAG API
After=network.target postgresql.service qdrant.service redis-server.service
Wants=postgresql.service qdrant.service redis-server.service

[Service]
Type=simple
User=ragadmin
Group=ragadmin
WorkingDirectory=/opt/tenbit-rag/src
Environment=RAG_ENV=production
Environment=RAG_CONFIG_PATH=/etc/tenbit-rag/config.json
ExecStart=/opt/tenbit-rag/venv/bin/uvicorn \
    rbs_rag.web.server:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 4 \
    --log-level info
Restart=always
RestartSec=10
StandardOutput=append:/var/log/tenbit-rag/api.stdout.log
StandardError=append:/var/log/tenbit-rag/api.stderr.log
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### 5.6 Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name rag.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name rag.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/rag.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rag.yourdomain.com/privkey.pem;

    client_max_body_size 100M;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 120s;

        # Rate limiting
        limit_req zone=api burst=20 nodelay;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Rate limit zone definition (in http block of nginx.conf)
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
```

```bash
# Get SSL
certbot --nginx -d rag.yourdomain.com

# Enable and start everything
systemctl daemon-reload
systemctl enable rag-api
systemctl start rag-api
nginx -t && systemctl reload nginx
```

### 5.7 Log Rotation

```bash
cat > /etc/logrotate.d/tenbit-rag << 'EOF'
/var/log/tenbit-rag/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

---

## 6. Security & Backup

### Security Hardening Checklist
- [ ] SSH key-only authentication, root login disabled
- [ ] UFW firewall: only 22, 80, 443 open
- [ ] Fail2ban configured for SSH and Nginx
- [ ] PostgreSQL bound to 127.0.0.1 only
- [ ] Redis bound to 127.0.0.1 with requirepass set
- [ ] Qdrant bound to 127.0.0.1 (no public API)
- [ ] Auto security updates enabled (`unattended-upgrades`)
- [ ] AIDE or Tripwire file integrity monitoring
- [ ] `auditd` for system call logging

### Backup Automation

```bash
#!/bin/bash
# /usr/local/bin/backup-rag.sh

BACKUP_DIR="/backups/tenbit-rag"
DATE=$(date +%Y%m%d_%H%M%S)
S3_BUCKET="s3://rag-backups"

mkdir -p "$BACKUP_DIR"

# PostgreSQL
pg_dump -U rag_user rag > "$BACKUP_DIR/pg_$DATE.sql"
gzip "$BACKUP_DIR/pg_$DATE.sql"

# Qdrant snapshot
curl -X POST "http://localhost:6333/snapshots"

# Application data
tar -czf "$BACKUP_DIR/data_$DATE.tar.gz" /opt/tenbit-rag/data

# Upload to S3 (or Backblaze B2)
aws s3 cp "$BACKUP_DIR" "$S3_BUCKET/" --recursive --exclude "*" --include "*$DATE*"

# Cleanup local (older than 7 days)
find "$BACKUP_DIR" -mtime +7 -delete
```

**Cron:** `0 3 * * * /usr/local/bin/backup-rag.sh`

---

## 7. Production Readiness Checklist

- [ ] Server hardened (SSH, firewall, fail2ban, auto-updates)
- [ ] PostgreSQL installed with production tuning
- [ ] Redis configured with password and memory limit
- [ ] Qdrant installed and bound to localhost
- [ ] Python venv created from requirements
- [ ] Systemd service configured with auto-restart
- [ ] Nginx reverse proxy with SSL
- [ ] Rate limiting configured on API endpoints
- [ ] Log rotation configured
- [ ] Backup scripts tested with restore verification
- [ ] Monitoring (Prometheus node_exporter + Grafana)
- [ ] Health endpoint returning 200 (`/health`)
- [ ] Load test performed (100 concurrent users minimum)
- [ ] Rollback procedure documented (previous venv + code backup)
