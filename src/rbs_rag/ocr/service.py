"""OCR Service singleton for the RAG pipeline."""
from __future__ import annotations

import os
from rbs_rag.ocr.engine import OCREngine
from rbs_rag.services.ocr_service import OCRService

_ocr_service: OCRService | None = None


def get_ocr_service() -> OCRService:
    """Get or create the global OCR service instance."""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService(
            mistral_api_key=os.getenv("MISTRAL_API_KEY", ""),
            languages=os.getenv("OCR_LANGUAGES", "en").split(","),
            use_gpu=os.getenv("USE_GPU", "false").lower() == "true",
            primary_engine=os.getenv("PRIMARY_OCR_ENGINE", "paddle"),
            dpi=int(os.getenv("OCR_RENDER_DPI", "150")),
        )
    return _ocr_service


def init_ocr_service(
    mistral_api_key: str = "",
    languages: list[str] = None,
    use_gpu: bool = False,
    primary_engine: str = "paddle",
    dpi: int = 150,
) -> OCRService:
    """Initialize the OCR service with custom configuration."""
    global _ocr_service
    _ocr_service = OCRService(
        mistral_api_key=mistral_api_key,
        languages=languages or ["en"],
        use_gpu=use_gpu,
        primary_engine=primary_engine,
        dpi=dpi,
    )
    return _ocr_service