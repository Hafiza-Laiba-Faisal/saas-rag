"""Pydantic models for health and version response envelopes."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str = Field(
        ..., description="Service status: 'ok' or 'degraded'"
    )
    ocr_engine_ready: bool = Field(
        ..., description="Whether the OCR engine is initialized"
    )


class VersionResponse(BaseModel):
    """Response body for GET /version."""

    service_version: str = Field(..., description="OCR service version string")
    python_version: str = Field(..., description="Python runtime version string")
    paddleocr_version: str = Field(..., description="PaddleOCR library version string")
