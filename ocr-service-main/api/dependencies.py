"""FastAPI dependency injection providers."""
from __future__ import annotations
from typing import Annotated
from fastapi import Depends, HTTPException, Request
from config.settings import Settings, get_settings as _get_settings
from ocr.engines.orchestrator import OCROrchestrator
from services.image_service import ImageOCRService
from services.pdf_service import PDFOCRService
from services.result_builder import ResultBuilder
from services.batch_service import BatchProcessor


def get_settings() -> Settings:
    return _get_settings()


def get_orchestrator(request: Request) -> OCROrchestrator:
    """Return the singleton OCROrchestrator from app.state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None or not orchestrator.available_engines:
        raise HTTPException(
            status_code=503,
            detail={
                "request_id": "",
                "error_type": "ENGINE_UNAVAILABLE",
                "message": (
                    "No OCR engines are available. "
                    "Set MISTRAL_API_KEY in .env or install paddleocr."
                ),
            },
        )
    return orchestrator


def get_result_builder() -> ResultBuilder:
    return ResultBuilder()


def get_image_service(
    orchestrator: Annotated[OCROrchestrator, Depends(get_orchestrator)],
    result_builder: Annotated[ResultBuilder, Depends(get_result_builder)],
) -> ImageOCRService:
    return ImageOCRService(orchestrator, result_builder)


def get_pdf_service(
    orchestrator: Annotated[OCROrchestrator, Depends(get_orchestrator)],
    result_builder: Annotated[ResultBuilder, Depends(get_result_builder)],
) -> PDFOCRService:
    return PDFOCRService(orchestrator, result_builder)


def get_batch_processor(
    image_service: Annotated[ImageOCRService, Depends(get_image_service)],
    pdf_service: Annotated[PDFOCRService, Depends(get_pdf_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BatchProcessor:
    return BatchProcessor(image_service, pdf_service, settings)
