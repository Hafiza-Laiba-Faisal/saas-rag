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
        transformers \
        curl_cffi \
        playwright

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 \
    libnspr4 libnss3 libu2f-udev libvulkan1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
    libxrandr2 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Install Playwright Chromium browser
RUN playwright install chromium

COPY src/ src/
COPY docker/ docker/
COPY .env.example .env

ENV PYTHONPATH=/app/src

RUN chmod +x docker/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
