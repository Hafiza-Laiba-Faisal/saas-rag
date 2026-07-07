"""FastAPI application entry point."""
from __future__ import annotations
import sys
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from config.settings import get_settings
from schemas.errors import ErrorResponse
from utils.logger import get_logger
from utils.request_id import generate_request_id
from api.middleware import RequestLoggingMiddleware
from api.routers import ocr as ocr_router
from api.routers import health as health_router
from api.routers import benchmark as benchmark_router
from api.routers import advanced as advanced_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize OCR engines on startup; clean up on shutdown."""
    settings = get_settings()
    logger.info("Starting OCR service, initializing OCR engines...")

    engines = []

    # 1. Try Mistral (primary)
    try:
        from ocr.engines.mistral_engine import MistralOCREngine
        mistral = MistralOCREngine(api_key=settings.mistral_api_key)
        if mistral.is_available():
            engines.append(mistral)
            logger.info("MistralOCREngine added as primary engine")
        else:
            logger.info("MistralOCREngine not available (no API key?), skipping")
    except Exception as e:
        logger.warning("Could not initialize MistralOCREngine: %s", e)

    # 2. Try PaddleOCR (fallback)
    try:
        from ocr.engines.paddle_engine import PaddleOCREngine
        langs = [lang.strip() for lang in settings.ocr_languages.split(",")]
        paddle = PaddleOCREngine(languages=langs, use_gpu=settings.use_gpu)
        if paddle.is_available():
            engines.append(paddle)
            logger.info("PaddleOCREngine added as fallback engine")
        else:
            logger.info("PaddleOCREngine not available, skipping")
    except Exception as e:
        logger.warning("Could not initialize PaddleOCREngine: %s", e)

    from ocr.engines.orchestrator import OCROrchestrator
    app.state.orchestrator = OCROrchestrator(engines)
    app.state.ocr_engine_ready = len(engines) > 0

    if engines:
        logger.info("OCR service ready with engines: %s",
                     [type(e).__name__ for e in engines])
    else:
        logger.warning("No OCR engines available — running in degraded mode")

    yield
    logger.info("OCR service shutting down")


app = FastAPI(
    title="OCR Service",
    description="Production-ready OCR microservice using PaddleOCR",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Rate Limiting ──────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Optional API Key Auth ──────────────────────────────────────
import os
from fastapi import Request as _Req

_API_KEY = os.getenv("OCR_API_KEY", "")  # empty = auth disabled

@app.middleware("http")
async def api_key_middleware(request: _Req, call_next):
    if _API_KEY:
        # Skip auth for health/version
        if request.url.path not in ("/health", "/version", "/docs", "/redoc", "/openapi.json"):
            key = request.headers.get("X-API-Key", "")
            if key != _API_KEY:
                from fastapi.responses import JSONResponse as _JR
                return _JR(status_code=401, content={"error": "Invalid or missing API key", "header": "X-API-Key"})
    return await call_next(request)

# Middleware
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(ocr_router.router)
app.include_router(health_router.router)
app.include_router(benchmark_router.router)
app.include_router(advanced_router.router)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID", generate_request_id())
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            request_id=request_id,
            error_type="HTTP_ERROR",
            message=str(exc.detail),
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID", generate_request_id())
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            request_id=request_id,
            error_type="VALIDATION_ERROR",
            message="Request validation failed",
            detail=str(exc.errors()),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID", generate_request_id())
    logger.error(
        "Unhandled exception: %s\n%s",
        exc,
        traceback.format_exc(),
        extra={"request_id": request_id},
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            request_id=request_id,
            error_type="INTERNAL_ERROR",
            message="An internal server error occurred",
        ).model_dump(),
    )
