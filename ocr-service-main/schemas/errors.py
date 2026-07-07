"""Pydantic models for structured error responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Structured error body returned on all non-2xx responses."""

    request_id: str = Field(..., description="Unique request identifier")
    error_type: str = Field(
        ..., description="Machine-readable error type (e.g. UNSUPPORTED_FORMAT)"
    )
    message: str = Field(..., description="Human-readable error description")
    detail: str | None = Field(
        default=None, description="Optional additional context or stack info"
    )
