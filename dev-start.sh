#!/usr/bin/env bash
# TenBit RAG — Dev Launcher
# Usage: ./dev-start.sh
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Docker containers
docker compose up -d qdrant redis scraper_service ocr_service

# 2. Open terminal helper — tries konsole → gnome-terminal → xterm → fallback bg
open_term() {
  local title="$1"
  local cmd="$2"
  if command -v konsole &>/dev/null; then
    konsole --title "$title" -e bash -c "$cmd; exec bash" &
  elif command -v gnome-terminal &>/dev/null; then
    gnome-terminal --window --title="$title" -- bash -c "$cmd; exec bash" &
  elif command -v xterm &>/dev/null; then
    xterm -title "$title" -e bash -c "$cmd; exec bash" &
  else
    echo "No terminal emulator found (konsole/gnome-terminal/xterm) — running '$title' in background, logs won't be visible separately."
    bash -c "$cmd" &
  fi
}

# 3. Directory sanity checks — fail fast with a clear message instead of a silent cd error
[ -d "$ROOT/.venv" ] || { echo "Missing: $ROOT/.venv (create it with: python -m venv .venv && .venv/bin/pip install -e .)"; exit 1; }
[ -d "$ROOT/chic-interface-design" ] || { echo "Missing: $ROOT/chic-interface-design"; exit 1; }

# Bind-mounted crawl output must exist and be user-owned BEFORE the scraper
# container starts — otherwise Docker creates it as root and the scraper
# (running as UID 1000) hits "Permission denied" writing crawl results.
mkdir -p "$ROOT/scraper-service/crawl_output"

# 4. Backend (Python) — new terminal window (skip if a backend is already on :3001)
if curl -s -o /dev/null -m 1 http://127.0.0.1:3001/api/v1/health; then
  echo "Backend already running on http://localhost:3001 — skipping backend terminal."
else
  open_term "RAG Backend" "cd '$ROOT' && \
    set -a && . ./.env && set +a && \
    RAG_ROOT_DIR='$ROOT/.rbs_rag' \
    QDRANT_HOST=localhost \
    QDRANT_PORT=6333 \
    RAG_REDIS_HOST=localhost \
    REDIS_HOST=localhost \
    REDIS_PORT=6379 \
    REDIS_ENABLED=true \
    RAG_LLM_MIN_INTERVAL="${RAG_LLM_MIN_INTERVAL:-1.5}" \
    SCRAPER_SERVICE_URL=http://localhost:8002 \
    PYTHONPATH='$ROOT/src' \
    .venv/bin/uvicorn rbs_rag.web.server:app --host 127.0.0.1 --port 3001 --reload --reload-dir '$ROOT/src'"
fi

# 5. Frontend — new terminal window (skip if a dev server is already on :5173)
if curl -s -o /dev/null -m 1 http://127.0.0.1:5173; then
  echo "Frontend already running on http://localhost:5173 — skipping frontend terminal."
else
  open_term "RAG Frontend" "cd '$ROOT/chic-interface-design' && npm run dev"
fi

# 6. Docker logs — new terminal window (scraper + ocr, since these run detached and had no visible logs)
open_term "Docker Logs (scraper + ocr)" "docker compose logs -f scraper_service ocr_service"

echo "
  Frontend  → http://localhost:5173
  Backend   → http://localhost:3001
  Qdrant    → http://localhost:6333
  Scraper   → http://localhost:8002
  OCR       → http://localhost:8000
"
