#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}==============================================${NC}"
echo -e "${CYAN}  TenBit RAG Platform — Full Bootstrap Setup${NC}"
echo -e "${CYAN}==============================================${NC}"
echo ""

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORK_DIR"

# ──────────────────────────────────────────────
# 1. Check OS & Package Manager
# ──────────────────────────────────────────────
OS="$(uname -s)"
PKG_MANAGER=""
INSTALL_CMD=""
if command -v apt-get &>/dev/null; then
    PKG_MANAGER="apt"; INSTALL_CMD="sudo apt-get install -y"
elif command -v yum &>/dev/null; then
    PKG_MANAGER="yum"; INSTALL_CMD="sudo yum install -y"
elif command -v brew &>/dev/null; then
    PKG_MANAGER="brew"; INSTALL_CMD="brew install"
elif command -v pacman &>/dev/null; then
    PKG_MANAGER="pacman"; INSTALL_CMD="sudo pacman -S --noconfirm"
else
    warn "Unknown package manager. Some prerequisites may need manual install."
fi
info "OS: $OS | Package Manager: ${PKG_MANAGER:-none}"

# ──────────────────────────────────────────────
# 2. Python 3.11+
# ──────────────────────────────────────────────
info "Checking Python..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
        MAJ=$(echo "$VER" | cut -d. -f1)
        MIN=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJ" -ge 3 ] && [ "$MIN" -ge 11 ] 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    warn "Python 3.11+ not found. Attempting install..."
    if [ -n "$PKG_MANAGER" ]; then
        $INSTALL_CMD python3 python3-pip python3-venv
        PYTHON="python3"
    else
        fail "Please install Python 3.11+ manually, then re-run this script."
    fi
fi
info "Python: $($PYTHON --version 2>&1)"

# ──────────────────────────────────────────────
# 3. Docker
# ──────────────────────────────────────────────
info "Checking Docker..."
if ! command -v docker &>/dev/null; then
    warn "Docker not found. Installing Docker..."
    if [ "$OS" = "Linux" ]; then
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        warn "You may need to log out and back in for Docker group to take effect."
    else
        fail "Please install Docker Desktop from https://docker.com, then re-run."
    fi
fi
ok "Docker: $(docker --version 2>&1)"

# ──────────────────────────────────────────────
# 4. Docker Compose
# ──────────────────────────────────────────────
info "Checking Docker Compose..."
if ! docker compose version &>/dev/null && ! command -v docker-compose &>/dev/null; then
    warn "Docker Compose not found. Installing..."
    if command -v docker &>/dev/null && docker plugin ls 2>/dev/null | grep -q compose; then
        : # docker compose plugin already present via Docker install
    else
        COMPOSE_VER="v2.27.0"
        sudo curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi
fi
DCOMPOSE="docker compose"
if ! docker compose version &>/dev/null; then
    DCOMPOSE="docker-compose"
fi
ok "Docker Compose: $($DCOMPOSE version 2>&1 | head -1)"

# ──────────────────────────────────────────────
# 5. .env file
# ──────────────────────────────────────────────
info "Checking .env file..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        warn ".env created from .env.example — please review and update secrets (API keys, passwords)."
    elif [ -f .env.docker ]; then
        cp .env.docker .env
        warn ".env created from .env.docker — please review and update secrets."
    else
        warn "No .env template found. Creating minimal .env..."
        cat > .env <<'ENVEOF'
# --- LLM Provider ---
LLM_API_KEY=
LLM_MODEL=gemini-2.5-flash-lite
LLM_BASE_URL=
# --- DeepCrawl ---
DEEPCRAWL_API_KEY=
# --- Admin Auth ---
RAG_ADMIN_JWT_SECRET=my-super-secret-jwt-key-change-in-production-1234
RAG_ADMIN_PASSWORD=admin
# --- Encryption (set a random 32-char hex key) ---
RAG_ENCRYPTION_KEY=
# --- Redis ---
REDIS_PASSWORD=
ENVEOF
    fi
else
    ok ".env file exists."
fi

# ──────────────────────────────────────────────
# 6. SSL Certificates
# ──────────────────────────────────────────────
info "Checking SSL certificates..."
SSL_DIR="nginx/ssl"
KEY_FILE="$SSL_DIR/server.key"
CRT_FILE="$SSL_DIR/server.crt"
if [ ! -f "$KEY_FILE" ] || [ ! -f "$CRT_FILE" ]; then
    warn "SSL certs missing. Generating self-signed certificates..."
    mkdir -p "$SSL_DIR"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY_FILE" -out "$CRT_FILE" \
        -subj "/C=PK/ST=Islamabad/L=Islamabad/O=TenBit/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1" 2>/dev/null || \
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY_FILE" -out "$CRT_FILE" \
        -subj "/C=PK/ST=Islamabad/L=Islamabad/O=TenBit/CN=localhost"
    ok "Self-signed SSL certs created."
else
    ok "SSL certs found."
fi

# ──────────────────────────────────────────────
# 7. Python Dependencies (for local tools/scripts)
# ──────────────────────────────────────────────
info "Checking Python dependencies..."
if [ -f pyproject.toml ]; then
    if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
        PIP="pip"
        command -v pip &>/dev/null || PIP="pip3"
        if $PIP show rbs-rag &>/dev/null 2>&1 || $PIP list 2>/dev/null | grep -qi rbs; then
            ok "Python deps already installed."
        else
            info "Installing Python dependencies..."
            $PIP install -e . 2>/dev/null || warn "Skipping local pip install (OK if running via Docker)."
        fi
    fi
fi

# ──────────────────────────────────────────────
# 8. Build React Admin UI
# ──────────────────────────────────────────────
UI_DIR="$(cd "$(dirname "$0")/.." && pwd)/chic-interface-design"
NODE_STATIC="$(cd "$(dirname "$0")" && pwd)/rbs-rag-node/static"

if [ -d "$UI_DIR" ]; then
    info "Building React Admin UI from: $UI_DIR"
    if command -v node &>/dev/null && command -v npm &>/dev/null; then
        (
            cd "$UI_DIR"
            npm install --silent 2>/dev/null || true
            npx vite build --config vite.spa.config.ts 2>&1 | tail -5
            rm -rf "$NODE_STATIC"/*
            cp -r dist-spa/* "$NODE_STATIC"/
            ok "React UI built and deployed to: $NODE_STATIC"
        )
    else
        warn "Node.js/npm not found — skipping UI build. Existing static files will be used."
    fi
else
    warn "chic-interface-design not found at $UI_DIR — skipping UI build."
fi

# ──────────────────────────────────────────────
# 9. Pull & Build Docker Images
# ──────────────────────────────────────────────
info "Pulling base images..."
$DCOMPOSE pull 2>&1 | tail -3 || true

info "Building images..."
$DCOMPOSE build 2>&1 | tail -5

# ──────────────────────────────────────────────
# 10. Start Services
# ──────────────────────────────────────────────
info "Cleaning old containers..."
$DCOMPOSE down --remove-orphans 2>/dev/null || true

info "Starting all services..."
$DCOMPOSE up -d --force-recreate

# ──────────────────────────────────────────────
# 11. Health Check
# ──────────────────────────────────────────────
echo ""
info "Waiting for services to become healthy..."
for i in $(seq 1 15); do
    sleep 2
    HEALTH=$(curl -sk https://localhost/health 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        ok "All services healthy!"
        break
    fi
    echo "  Waiting... ($(( i * 2 ))s)"
done

if ! curl -sk https://localhost/health 2>/dev/null | grep -q '"status":"ok"'; then
    warn "Health check did not confirm all services ready. Check logs below."
fi

echo ""
echo -e "${CYAN}==============================================${NC}"
echo -e "${GREEN}  ✅ TenBit RAG Platform is running!${NC}"
echo ""
echo -e "  ${CYAN}Dashboard:${NC}  https://localhost/"
echo -e "  ${CYAN}Health API:${NC} https://localhost/health"
echo ""
echo -e "  ${YELLOW}Default Admin Login:${NC}"
echo -e "    Username: admin"
echo -e "    Password: admin"
echo -e "  ${YELLOW}(Change RAG_ADMIN_PASSWORD in .env for production)${NC}"
echo ""
echo -e "  ${YELLOW}Next Steps:${NC}"
echo -e "    1. Open ${CYAN}https://localhost/${NC} in your browser (accept self-signed cert warning)"
echo -e "    2. Login with admin/admin"
echo -e "    3. Create a tenant with your LLM API key"
echo -e "    4. Upload documents or scrape URLs"
echo -e "    5. Test chat in Playground"
echo ""
echo -e "  Logs below (Ctrl+C to stop watching, services keep running):"
echo -e "${CYAN}==============================================${NC}"
echo ""

$DCOMPOSE logs -f
