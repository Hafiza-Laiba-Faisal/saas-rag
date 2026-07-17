#!/usr/bin/env bash
set -e

echo "=== Stopping RAG Dev ==="

# Kill server from PID file
if [ -f .logs/server.pid ]; then
  kill "$(cat .logs/server.pid)" 2>/dev/null || true
  rm -f .logs/server.pid
fi

# Kill server by port
lsof -ti:3001 2>/dev/null | xargs kill -9 2>/dev/null || true

# Stop Qdrant
docker stop rag-qdrant 2>/dev/null || true

echo "  ✔ Stopped"
