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

# 4. Backend (Python) — new terminal window
open_term "RAG Backend" "cd '$ROOT' && set -a && . ./.env && set +a && RAG_ROOT_DIR='$ROOT/.rbs_rag' QDRANT_HOST=localhost RAG_REDIS_HOST=localhost SCRAPER_SERVICE_URL=http://localhost:8002 PYTHONPATH='$ROOT/src' .venv/bin/uvicorn rbs_rag.web.server:app --host 127.0.0.1 --port 3001 --reload"

# 5. Frontend — new terminal window
open_term "RAG Frontend" "cd '$ROOT/chic-interface-design' && npm run dev"

# 6. Docker logs — new terminal window (scraper + ocr, since these run detached and had no visible logs)
open_term "Docker Logs (scraper + ocr)" "docker compose logs -f scraper_service ocr_service"

echo "
  Frontend  → http://localhost:5173
  Backend   → http://localhost:3001
  Qdrant    → http://localhost:6333
  Scraper   → http://localhost:8002
  OCR       → http://localhost:8000
"
