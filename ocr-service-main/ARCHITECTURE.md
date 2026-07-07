# Architecture

The OCR Service is built around a **Pluggable Strategy Pattern** — OCR engines are interchangeable components behind a unified interface. The system always tries the best available engine and falls back gracefully, ensuring continuous operation.

---

## High-Level Overview

```
┌─────────────────────────────────────────────────────┐
│                   Client / Script                   │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP  /  direct call
┌───────────────────────▼─────────────────────────────┐
│              FastAPI Application (main.py)          │
│  ┌─────────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ /ocr/image  │  │ /ocr/pdf │  │ /ocr/batch    │  │
│  └──────┬──────┘  └────┬─────┘  └───────┬───────┘  │
└─────────┼──────────────┼────────────────┼───────────┘
          │              │                │
┌─────────▼──────────────▼────────────────▼───────────┐
│               Service Layer                         │
│   ImageOCRService   PDFOCRService   BatchProcessor  │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│              OCROrchestrator                        │
│   1. Try MistralOCREngine  ──────────► Mistral API  │
│   2. On failure → PaddleOCREngine ──► local model   │
└─────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### `main.py` — Application Entry Point
- Initialises FastAPI with lifespan context
- On startup: instantiates `MistralOCREngine` and `PaddleOCREngine`, wraps them in `OCROrchestrator`, stores on `app.state`
- Registers middleware (CORS, request logging, API key auth, rate limiting)
- Mounts all routers

### `ocr/engines/orchestrator.py` — Engine Router
Central component that:
- Holds an ordered list of available engines
- On each request, iterates through engines until one succeeds
- Logs which engine was used and any fallback events
- Raises `RuntimeError` only if **all** engines fail

```python
OCROrchestrator([mistral_engine, paddle_engine])
# → tries mistral first, falls back to paddle on any exception
```

### `ocr/engines/base.py` — Engine Contract
Abstract base class every engine must implement:

```python
class BaseOCREngine(ABC):
    def is_available(self) -> bool: ...
    def process_image(self, image_data: bytes, filename: str) -> PageResult: ...
    def process_pdf(self, pdf_bytes: bytes, filename: str) -> List[PageResult]: ...
```

### `ocr/engines/mistral_engine.py` — Primary Engine
- Calls `mistral-ocr-latest` via `mistralai` SDK
- Sends files as base64-encoded data URLs
- Extracts: plain text, Markdown, HTML tables, hyperlinks
- Returns `List[PageResult]` matching our standard schema

### `ocr/engines/paddle_engine.py` — Fallback Engine
- Wraps the low-level `OCREngine` (PaddleOCR) with the `BaseOCREngine` interface
- For images: preprocesses → runs inference → builds `PageResult`
- For PDFs: delegates to `HybridPDFPipeline`
- Uses `onnxruntime` backend for Python 3.14 compatibility

### `ocr/engine.py` — Low-Level PaddleOCR Wrapper
- Initialises `PaddleOCR` once at startup (singleton)
- `run(image: np.ndarray) → List[OCRRegion]`
- Filters low-confidence results (< 0.5)
- Converts polygon output to axis-aligned bounding boxes

---

## PDF Processing — Hybrid Pipeline

For PaddleOCR-based PDF processing, `pdf/pipeline.py` implements a smart two-pass approach:

```
PDF bytes
    │
    ├── Page has embedded text?
    │       ├── YES → Extract text directly (fast, accurate)
    │       └── NO  → Render page to image at configured DPI
    │                   └── Run OCR on rendered image
    │
    └── Merge results per page → List[PageResult]
```

**Key components:**
- `pdf/text_extractor.py` — native text extraction via PyMuPDF
- `pdf/page_renderer.py` — renders PDF pages to numpy arrays
- `pdf/image_extractor.py` — extracts embedded images
- `pdf/image_processor.py` — runs OCR on individual images
- `pdf/decorative_filter.py` — skips logos/decorative elements

---

## Batch CLI Pipeline

`process_error_files.py` uses the same engine classes directly (no HTTP):

```
Input directory
    │
    ├── .pdf  ──────────────────► process_pdf_bytes()
    │                                   │
    │                             MistralOCREngine.process_pdf()
    │                             → fail → PaddleOCREngine.process_pdf()
    │
    ├── .pptx / .ppt  ──────────► LibreOffice → PDF → process_pdf_bytes()
    │
    └── .xlsx / .xls  ──────────► openpyxl direct parse (no OCR)
    
    └── All results → results.json + summary.csv + texts/*.txt
```

---

## Data Flow — Single Request

```
POST /ocr/pdf
    │
    ├── FileValidator.validate_upload()      ← size + MIME check
    │
    ├── PDFOCRService.process()
    │       │
    │       ├── OCROrchestrator.process_pdf()
    │       │       │
    │       │       ├── MistralOCREngine.process_pdf()   ← try primary
    │       │       │       └── _parse_response() → List[PageResult]
    │       │       │
    │       │       └── (on failure) PaddleOCREngine.process_pdf()
    │       │               └── HybridPDFPipeline.process() → List[PageResult]
    │       │
    │       ├── EntityExtractor.extract()   ← URLs, emails, phones
    │       │
    │       └── ResultBuilder.build_ocr_result()
    │
    └── OCRResult (JSON response)
```

---

## Schemas (`schemas/ocr.py`)

```
OCRResult
├── request_id: str
├── filename: str
├── processing_time_ms: float
├── ocr_duration_ms: float
└── pages: List[PageResult]
        ├── page_number: int
        ├── full_text: str
        ├── markdown: str | None         (Mistral only)
        ├── tables: List[str]            (HTML, Mistral only)
        ├── hyperlinks: List[str]        (Mistral only)
        ├── paragraphs: List[str]
        ├── lines: List[str]
        ├── words: List[str]
        ├── regions: List[OCRRegion]     (PaddleOCR only)
        │       ├── text: str
        │       ├── confidence: float
        │       └── bounding_box: [x1, y1, x2, y2]
        └── entities: ExtractedEntities
                ├── urls: List[str]
                ├── emails: List[str]
                └── phone_numbers: List[str]
```

---

## Configuration (`config/settings.py`)

All settings are loaded from environment variables / `.env` via `pydantic-settings`. Invalid values raise at startup (fail-fast).

| Variable | Default | Description |
|---|---|---|
| `MISTRAL_API_KEY` | `""` | Mistral cloud API key |
| `MAX_FILE_SIZE_MB` | `50` | Max upload size |
| `OCR_LANGUAGES` | `en,ur,ar` | PaddleOCR language list |
| `USE_GPU` | `false` | Enable CUDA inference |
| `PAGE_RENDER_DPI` | `150` | DPI for PDF rendering |
| `MIN_TEXT_CHARS_THRESHOLD` | `20` | Min chars to skip OCR on a page |
| `MIN_IMAGE_DPI` | `150` | Images below this DPI are upscaled |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Dependency Map

```
main.py
  └── api/routers/ocr.py
        └── api/dependencies.py
              ├── OCROrchestrator  ←── [MistralOCREngine, PaddleOCREngine]
              ├── ImageOCRService
              ├── PDFOCRService
              └── BatchProcessor
                    ├── ImageOCRService
                    ├── PDFOCRService
                    └── FileValidator

process_error_files.py (scripts/process_error_files.py)
  ├── MistralOCREngine  (direct)
  ├── PaddleOCREngine   (direct, fallback)
  └── openpyxl          (Excel, no OCR)
```
