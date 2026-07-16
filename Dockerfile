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
        transformers

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY src/ src/
COPY docker/ docker/
COPY .env.example .env

ENV PYTHONPATH=/app/src

RUN chmod +x docker/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
