#!/bin/bash
set -e

cd /home/tenbitsolutions/chic-interface-design

echo "==> Installing dependencies..."
npm install

echo "==> Building SPA..."
npx vite build --config vite.spa.config.ts

echo "==> Deploying to Node static folder..."
STATIC_DIR="/home/tenbitsolutions/Documents/Tenbit/3-ongoing-projects/RAG/rbs-rag-node/static"
rm -rf $STATIC_DIR/*
cp -r dist-spa/* $STATIC_DIR/
cp public/favicon.ico $STATIC_DIR/ 2>/dev/null || true

echo "==> Done! Files in $STATIC_DIR:"
ls $STATIC_DIR/
