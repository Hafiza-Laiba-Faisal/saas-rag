# ── Stage 1: Build React SPA frontend ────────────────────────────────────────
FROM node:22-slim AS frontend-builder

WORKDIR /build
COPY chic-interface-design/package.json chic-interface-design/package-lock.json* ./
# Full install (NOT --omit=dev): vite/typescript are devDependencies, without them
# `npm run build:spa` fails and the image silently ships the stale committed
# dist-spa instead of a fresh build. Build errors must fail the image build.
RUN npm ci --ignore-scripts

COPY chic-interface-design/ .
# Fail fast: no 2>/dev/null, no `; mkdir -p` fallback. If the SPA build fails or
# produces no index.html the image build stops instead of deploying old UI.
RUN npm run build:spa && test -f dist-spa/index.html

# ── Stage 2: Python dependencies ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install \
        fastapi uvicorn[standard] pydantic pydantic-settings \
        python-multipart sqlite-utils httpx python-json-logger \
        pillow numpy \
        pypdf pymupdf openpyxl xlrd python-pptx \
        qdrant-client redis \
        opencv-python-headless beautifulsoup4 \
        cryptography pyjwt prometheus-client \
        curl_cffi \
        brotli

# ── Stage 3: Runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY src/ src/
COPY docker/ docker/
COPY .env.example .env

# Copy the freshly-built React SPA (never the stale committed dist-spa)
COPY --from=frontend-builder /build/dist-spa /app/chic-interface-design/dist-spa

ENV PYTHONPATH=/app/src
ENV RAG_SPA_DIR=/app/chic-interface-design/dist-spa

RUN chmod +x docker/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
