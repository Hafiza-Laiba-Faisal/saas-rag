#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UI_DIR="$ROOT_DIR/../chic-interface-design"
STATIC_DIR="$ROOT_DIR/static"

if [ ! -d "$UI_DIR" ]; then
  echo "[sync-frontend] React frontend not found at $UI_DIR"
  exit 1
fi

cd "$UI_DIR"
echo "[sync-frontend] Installing frontend deps..."
npm install --silent >/dev/null 2>&1 || true

echo "[sync-frontend] Building React SPA..."
npx vite build --config vite.spa.config.ts >/dev/null

echo "[sync-frontend] Syncing built assets to Node static folder..."
rm -rf "$STATIC_DIR"/*
cp -r dist-spa/* "$STATIC_DIR"/

echo "[sync-frontend] Frontend synced successfully"
