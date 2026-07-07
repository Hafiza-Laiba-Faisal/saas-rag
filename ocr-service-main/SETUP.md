# Setup Guide

Complete guide to install, configure, and run the OCR Service from scratch.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ (3.14 recommended) | Uses `onnxruntime` engine for PaddleOCR on 3.14 |
| `uv` | latest | Fast package installer — recommended |
| LibreOffice | any | Required for PPT/PPTX → PDF conversion |
| Mistral API Key | — | For primary cloud OCR engine |

### Install LibreOffice (if not already installed)
```bash
sudo apt install libreoffice   # Ubuntu/Debian
sudo dnf install libreoffice   # Fedora/RHEL
brew install --cask libreoffice  # macOS
```

### Install `uv` (if not already installed)
```bash
pip install uv
# or
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation

### 1. Clone the repository
```bash
git clone <repository_url>
cd ocr-service
```

### 2. Create virtual environment and install dependencies

Using `uv` (recommended):
```bash
uv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows

uv pip install -e ".[paddle]"     # installs all deps including PaddleOCR
uv pip install mistralai          # Mistral client
```

Using `pip`:
```bash
python -m venv venv
source venv/bin/activate

pip install -e ".[paddle]"
pip install mistralai
```

> **Python 3.14 note:** PaddleOCR wheels only exist for Python 3.9–3.11.
> The service automatically uses the `onnxruntime` backend on Python 3.14+,
> which is fully supported and requires no extra steps.

### 3. Configure environment variables
```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
# Required: Mistral cloud OCR (primary engine)
MISTRAL_API_KEY=your_mistral_api_key_here

# Optional tuning
MAX_FILE_SIZE_MB=50          # max upload size
OCR_LANGUAGES=en,ur,ar       # PaddleOCR language list (fallback)
USE_GPU=false                # set true if CUDA is available
PAGE_RENDER_DPI=150          # DPI for PDF page rendering
LOG_LEVEL=INFO               # DEBUG | INFO | WARNING | ERROR
```

Get your Mistral API key at: https://console.mistral.ai/

---

## Running the API Server

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Interactive API docs:
- Swagger UI → http://localhost:8000/docs
- ReDoc → http://localhost:8000/redoc
- Health check → http://localhost:8000/health

---

## Batch Processing Script

Process a whole folder of files (PDF, PPTX, XLSX) in one shot:

```bash
source venv/bin/activate

# Process the default error files folder
python scripts/process_error_files.py

# Custom input/output
python scripts/process_error_files.py \
  --input  /path/to/your/files \
  --output /path/to/results

# Process a single file
python scripts/process_error_files.py --file "report.pdf"

# Skip certain types
python scripts/process_error_files.py --skip-excel
python scripts/process_error_files.py --skip-ppt
```

### Output structure
```
output/
└── error_files_results/
    ├── results.json        ← full OCR data per file (pages, text, tables, markdown)
    ├── summary.csv         ← one row per file (engine, pages, words, status, time)
    └── texts/
        ├── file1.pdf.txt   ← plain extracted text
        ├── file2.xlsx.txt
        └── ...
```

### Supported file types

| Type | Engine | Notes |
|---|---|---|
| `.pdf` | Mistral → Paddle fallback | Cloud primary, local fallback |
| `.pptx` / `.ppt` | LibreOffice → Mistral → Paddle | Converted to PDF first |
| `.xlsx` / `.xls` | openpyxl | Direct parse, no OCR needed |

---

## Running Tests

```bash
source venv/bin/activate
pytest                       # all tests
pytest tests/unit/           # unit tests only
pytest tests/integration/    # integration tests only
pytest --cov=. --cov-report=html  # with HTML coverage report
```

---

## Project Structure

```
ocr-service/
│
├── main.py                      ← FastAPI app entry point & lifespan
├── pyproject.toml               ← Project metadata & dependencies
├── .env                         ← Local config (not committed)
├── .env.example                 ← Config template
│
├── scripts/
│   ├── process_error_files.py   ← Batch processing CLI script
│   └── test_pdf.py              ← Quick test script for engines
│
├── api/
│   ├── dependencies.py          ← FastAPI dependency injection
│   ├── middleware.py             ← Request logging middleware
│   └── routers/
│       ├── ocr.py               ← POST /ocr/image, /ocr/pdf, /ocr/batch
│       ├── health.py            ← GET /health
│       ├── advanced.py          ← Advanced processing endpoints
│       └── benchmark.py         ← Benchmark endpoints
│
├── ocr/
│   ├── engine.py                ← PaddleOCR wrapper (low-level)
│   └── engines/
│       ├── base.py              ← Abstract BaseOCREngine interface
│       ├── orchestrator.py      ← Routes to engines, handles fallback
│       ├── mistral_engine.py    ← Mistral cloud OCR engine
│       └── paddle_engine.py     ← PaddleOCR local engine
│
├── services/
│   ├── image_service.py         ← Image OCR orchestration
│   ├── pdf_service.py           ← PDF OCR orchestration
│   ├── batch_service.py         ← Multi-file batch processing
│   ├── result_builder.py        ← Assembles OCRResult objects
│   ├── advanced_processor.py    ← Advanced post-processing
│   └── validator.py             ← File validation & size checks
│
├── pdf/
│   ├── pipeline.py              ← HybridPDFPipeline (digital + scanned)
│   ├── page_renderer.py         ← PDF page → image renderer (PyMuPDF)
│   ├── text_extractor.py        ← Native PDF text extraction
│   ├── image_extractor.py       ← Embedded image extraction
│   ├── image_processor.py       ← Per-image OCR processing
│   └── decorative_filter.py     ← Filters out decorative images
│
├── schemas/
│   ├── ocr.py                   ← OCRResult, PageResult, BatchResult models
│   ├── errors.py                ← Error response models
│   └── responses.py             ← Generic response models
│
├── preprocessing/
│   └── preprocessor.py          ← Image preprocessing (denoise, binarize)
│
├── postprocessing/
│   ├── extractor.py             ← Entity extraction (URLs, emails, phones)
│   ├── table_parser.py          ← HTML table → structured data
│   └── japanese_corrector.py    ← Japanese text post-correction
│
├── config/
│   └── settings.py              ← Pydantic-settings config with validation
│
├── utils/
│   ├── logger.py                ← Structured JSON logger
│   ├── request_id.py            ← UUID request ID generator
│   └── language_detector.py     ← Language detection utility
│
├── table_detection/
│   └── models.py                ← Table detection models
│
├── tests/
│   ├── conftest.py              ← Shared fixtures
│   ├── unit/                    ← Unit tests
│   ├── integration/             ← API integration tests
│   └── fixtures/                ← Sample PDFs, images for tests
│
└── output/                      ← Batch script output (gitignored)
    └── error_files_results/
        ├── results.json
        ├── summary.csv
        └── texts/
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'pydantic_settings'`**
→ Run: `uv pip install pydantic-settings` inside the activated venv.

**`MistralOCREngine not available`**
→ Make sure `MISTRAL_API_KEY` is set in `.env`. Get one at https://console.mistral.ai/

**`LibreOffice conversion failed` on PPT files**
→ Install LibreOffice: `sudo apt install libreoffice`

**PaddleOCR model download is slow**
→ Models are cached at `~/.paddlex/official_models/` after first download.

**`Cannot open empty file` error**
→ The source file is 0 bytes — nothing to process.

**Mistral returns `Document type not supported`**
→ The PDF may be corrupted or use a non-standard encoding. PaddleOCR fallback will be attempted automatically.
