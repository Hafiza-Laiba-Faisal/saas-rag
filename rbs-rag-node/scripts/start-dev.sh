#!/usr/bin/env bash
set -eo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
MODE="${1:-dev}"
mkdir -p "$ROOT/.logs"

if [ "$MODE" = "test" ]; then
  echo "[test-mode] Running lightweight auth check only"
  if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
  fi
  node --import tsx scripts/auth-smoke.mjs
  exit 0
fi

# ── Kill old processes ──
echo "[1/6] Cleaning up old processes..."
lsof -ti:3001 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:6333  2>/dev/null | xargs kill -9 2>/dev/null || true
docker stop rag-qdrant 2>/dev/null || true
docker stop ocr_service 2>/dev/null || true
sleep 1
echo "  ✔ Done"

# ── Check .env ──
echo "[2/6] Checking .env ..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ⚠  Created .env from .env.example — edit it with your API keys!"
else
  echo "  ✔ Found .env"
fi

# ── Start Qdrant ──
echo "[3/6] Starting Qdrant (Docker)..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'rag-qdrant'; then
  echo "  ✔ Qdrant already running"
else
  docker run -d --rm --name rag-qdrant \
    -p 6333:6333 -p 6334:6334 \
    qdrant/qdrant:latest 2>&1 | sed 's/^/  /'
  echo "  ✔ Qdrant started"
  sleep 2
fi

# ── Start OCR Service ──
echo "[3.5/6] Starting OCR Service (Docker)..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'ocr_service'; then
  echo "  ✔ OCR Service already running"
else
  (cd ../ && docker compose up -d --build ocr_service 2>&1 | sed 's/^/  /')
  echo "  ✔ OCR Service started"
  sleep 2
fi

# ── Prisma setup + seed ──
echo "[4/6] Running Prisma setup + seed..."
npx prisma generate 2>&1 | sed 's/^/  /'
npx prisma migrate dev --name init 2>&1 | sed 's/^/  /'
npx tsx src/seed.ts 2>&1 | sed 's/^/  /'
echo "  ✔ Setup complete"

# ── Build React Admin UI ──
echo "[5/7] Building React Admin UI..."
UI_DIR="$ROOT/../chic-interface-design"
STATIC_DIR="$ROOT/static"

if [ -d "$UI_DIR" ]; then
  (
    cd "$UI_DIR"
    npm install --silent 2>/dev/null || true
    npx vite build --config vite.spa.config.ts 2>&1 | sed 's/^/  /'
    rm -rf "$STATIC_DIR"/*
    cp -r dist-spa/* "$STATIC_DIR"/
  )
  echo "  ✔ React UI built and deployed"
else
  echo "  ⚠  chic-interface-design not found — skipping UI build"
fi

# ── Build ──
echo "[6/7] Building TypeScript..."
npx tsc 2>&1 | sed 's/^/  /'
echo "  ✔ Build complete"

# ── Start services (background) ──
echo "[7/7] Starting services..."

# Start backend server (stream to terminal and save to log)
node dist/index.js > >(tee -a .logs/server.log) 2> >(tee -a .logs/server.log >&2) &
SERVER_PID=$!
echo $SERVER_PID > .logs/server.pid

echo "  ✔ Backend started (PID: $SERVER_PID)"

# Start frontend dev server (stream to terminal and save to log)
UI_DIR="$ROOT/../chic-interface-design"
if [ -d "$UI_DIR" ]; then
  (
    cd "$UI_DIR"
    npm install --silent 2>/dev/null || true
    npm run dev -- --host 0.0.0.0 --port 5173 > >(tee -a "$ROOT/.logs/frontend.log") 2> >(tee -a "$ROOT/.logs/frontend.log" >&2)
  ) &
  FRONTEND_PID=$!
  echo $FRONTEND_PID > "$ROOT/.logs/frontend.pid"
  echo "  ✔ Frontend started (PID: $FRONTEND_PID)"
else
  echo "  ⚠  Frontend app not found — skipping Vite server"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Services running in background"
echo ""
echo "  Backend: http://localhost:3001"
echo "  Frontend: http://localhost:5173"
echo "  Qdrant:  http://localhost:6333"
echo ""
echo "  ┌──────────────────────┬──────────────────────────┐"
echo "  │ View backend logs    │ tail -f .logs/server.log │"
echo "  │ View frontend logs   │ tail -f .logs/frontend.log │"
echo "  │ View Qdrant logs     │ docker logs -f rag-qdrant│"
echo "  │ Restart services     │ kill \$(cat .logs/server.pid) \$(cat .logs/frontend.pid) && $0  │"
echo "  │ Stop everything      │ ./scripts/stop-dev.sh    │"
echo "  └──────────────────────┴──────────────────────────┘"
echo ""
echo "  Quick start: open http://localhost:5173"
echo "═══════════════════════════════════════════════════════"
