# ── Stage 1: Build React SPA frontend ────────────────────────────────────────
FROM node:22-slim AS frontend-builder

WORKDIR /build
COPY chic-interface-design/package.json chic-interface-design/package-lock.json* ./
RUN npm ci --omit=dev --ignore-scripts 2>/dev/null || npm install --omit=dev

COPY chic-interface-design/ .
RUN npm run build:spa 2>/dev/null; mkdir -p /build/dist-spa

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

# Copy React SPA build (fallback to old static if not built)
COPY --from=frontend-builder /build/dist-spa /app/chic-interface-design/dist-spa

ENV PYTHONPATH=/app/src
ENV RAG_SPA_DIR=/app/chic-interface-design/dist-spa

RUN chmod +x docker/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
