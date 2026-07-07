"""Health and version endpoints."""
import sys
from fastapi import APIRouter, Request
from schemas.responses import HealthResponse, VersionResponse
from config.settings import get_settings

router = APIRouter(tags=["Health"])

@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    engine_ready = (
        getattr(request.app.state, "ocr_engine_ready", False) and
        getattr(request.app.state, "ocr_engine", None) is not None
    )
    return HealthResponse(
        status="ok" if engine_ready else "degraded",
        ocr_engine_ready=engine_ready,
    )

@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    settings = get_settings()
    try:
        import paddleocr
        paddle_version = getattr(paddleocr, "__version__", "unknown")
    except ImportError:
        paddle_version = "not installed"
    return VersionResponse(
        service_version=settings.service_version,
        python_version=sys.version,
        paddleocr_version=paddle_version,
    )
