# Features

A production-ready OCR microservice built on FastAPI with a pluggable engine architecture, cloud-primary processing, and local fallback.

---

## 1. Pluggable OCR Engine Architecture

Built on a **Strategy Pattern** — engines are swappable without touching application logic.

| Engine | Role | Backend |
|---|---|---|
| `MistralOCREngine` | Primary | Mistral cloud API (`mistral-ocr-latest`) |
| `PaddleOCREngine` | Fallback | Local inference via `onnxruntime` |

The `OCROrchestrator` tries engines in order. If the primary fails (network issue, API limit, unsupported file), it automatically falls back to the next available engine — zero downtime.

---

## 2. Broad File Format Support

### Via REST API
| Format | Endpoint |
|---|---|
| Images (PNG, JPEG, WEBP, BMP, TIFF) | `POST /ocr/image` |
| PDFs (digital & scanned) | `POST /ocr/pdf` |
| Multiple files at once | `POST /ocr/batch` |

### Via Batch CLI Script (`process_error_files.py`)
| Format | Engine | Notes |
|---|---|---|
| `.pdf` | Mistral → Paddle | Full page OCR |
| `.pptx` / `.ppt` | LibreOffice → Mistral → Paddle | Converted to PDF first |
| `.xlsx` / `.xls` | openpyxl | Direct cell extraction, no OCR |

---

## 3. Rich Structured Output

Every response includes:
- `full_text` — plain text of the entire document
- `markdown` — formatted Markdown (Mistral only)
- `tables` — extracted tables in **HTML format** (Mistral only)
- `hyperlinks` — extracted URLs (Mistral only)
- `paragraphs` / `lines` / `words` — split text at different granularities
- `regions` — bounding boxes + confidence scores per text region (PaddleOCR)
- `entities` — auto-extracted URLs, emails, phone numbers
- `processing_time_ms` — per-request timing

---

## 4. Hybrid PDF Pipeline

For PDFs processed via PaddleOCR, a smart hybrid pipeline:
- Extracts **native text** from digital PDF pages directly (fast, accurate)
- Detects **scanned pages** (low character count) and renders them to images
- Applies **OCR** only where needed — efficient and accurate
- Configurable threshold: `MIN_TEXT_CHARS_THRESHOLD` in `.env`

---

## 5. Intelligent Image Preprocessing

Applied automatically before PaddleOCR inference:
- Grayscale conversion and adaptive binarization
- Noise reduction and contrast enhancement
- Dynamic upscaling for low-DPI images (`MIN_IMAGE_DPI` setting)
- Orientation correction support

---

## 6. Batch Processing

**REST API batch endpoint** (`POST /ocr/batch`):
- Upload multiple files in one multipart request
- Returns per-file results + aggregate counts (successful / failed)
- Failed files don't block others — errors are captured per-file

**CLI batch script** (`process_error_files.py`):
- Processes an entire directory of mixed file types
- Saves results to: `results.json`, `summary.csv`, per-file `.txt`
- Progress and timing printed to console

---

## 7. Advanced Table Extraction

- Extracts tables in **HTML** format for frontend rendering
- Handles merged cells, nested headers, and multi-column layouts
- `postprocessing/table_parser.py` converts HTML tables to structured dicts

---

## 8. Entity Extraction

Automatically extracted from all OCR output:
- URLs and hyperlinks
- Email addresses
- Phone numbers

---

## 9. Production-Grade API

- **Rate limiting** — 60 requests/minute per IP (configurable via `slowapi`)
- **API key auth** — optional `X-API-Key` header auth (`OCR_API_KEY` env var)
- **CORS** — enabled for all origins by default
- **Request logging** — structured JSON logs with request IDs
- **Health endpoint** — `GET /health` with engine availability status
- **Validation errors** — clear 422 responses with field-level detail
- **File size limits** — configurable `MAX_FILE_SIZE_MB`

---

## 10. Observability

- Structured JSON logging via `python-json-logger`
- Per-request `X-Request-ID` tracing
- `processing_time_ms` and `ocr_duration_ms` in every response
- Sentry SDK integration available (add `SENTRY_DSN` to `.env`)
