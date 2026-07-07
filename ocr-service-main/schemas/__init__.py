"""Pydantic schema package for the OCR service."""

from schemas.errors import ErrorResponse
from schemas.ocr import (
    BatchResult,
    ExtractedEntities,
    FileErrorResult,
    OCRRegion,
    OCRResult,
    PageResult,
)
from schemas.responses import HealthResponse, VersionResponse

__all__ = [
    # OCR data models
    "OCRRegion",
    "ExtractedEntities",
    "PageResult",
    "OCRResult",
    "FileErrorResult",
    "BatchResult",
    # Response models
    "HealthResponse",
    "VersionResponse",
    # Error models
    "ErrorResponse",
]
