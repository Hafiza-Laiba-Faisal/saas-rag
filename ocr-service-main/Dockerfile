# =============================================================================
# OCR Service — Dockerfile
# =============================================================================
# Multi-stage build for minimal final image size
# =============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir --prefix=/install \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.5.0" \
    "python-multipart>=0.0.12" \
    "httpx>=0.27.0" \
    "python-json-logger>=2.0.7" \
    "pillow>=11.0.0" \
    "numpy>=1.26.0" \
    "slowapi>=0.1.9" \
    "opencv-python-headless>=4.9.0.80" \
    "pypdf>=4.0" \
    "pymupdf>=1.24.3" \
    "paddleocr>=3.0.0" \
    "onnxruntime>=1.18.0" \
    "mistralai>=1.0.0"

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install runtime system dependencies (for OpenCV, PDF processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -r ocr && useradd -r -g ocr -d /app -s /bin/false ocr

# Copy application source
COPY . .

# Create necessary directories
RUN mkdir -p /app/uploads /app/output && chown -R ocr:ocr /app

# Switch to non-root user
USER ocr

# Expose the API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]