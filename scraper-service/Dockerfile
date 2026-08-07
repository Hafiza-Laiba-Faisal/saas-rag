FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 \
    libnspr4 libnss3 libu2f-udev libvulkan1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    xdg-utils ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN playwright install chromium 2>/dev/null || true

COPY . .

# The container runs as UID 1000 (docker-compose `user: ${UID:-1000}`), so the
# data/downloads dirs must be owned by that UID — otherwise the named volume
# mounted over them comes up root-owned and writes fail with "Permission denied".
RUN mkdir -p /app/data /app/downloads && chown -R 1000:1000 /app/data /app/downloads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:8000/ || exit 1

# Single worker: the scraper keeps crawl jobs, rate limits and browser pools
# in process-local memory. With --workers 2, job/status state is not shared
# between workers (job_id polls 404) and Playwright/Chromium init runs twice,
# appearing to "loop" on startup. Scale via extra containers, not workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
