"""
Shared base response schemas.
Every endpoint returns a consistent envelope — success, data, errors, metrics.
"""

from __future__ import annotations
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    stage: str
    reason: str
    detail: str = ""


class Metrics(BaseModel):
    fetch_time_ms:   float = 0.0
    parse_time_ms:   float = 0.0
    extract_time_ms: float = 0.0
    rendered:        bool  = False


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data:    T | None = None
    errors:  list[ErrorDetail] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)

    @classmethod
    def ok(cls, data: T, metrics: Metrics | None = None) -> "ApiResponse[T]":
        return cls(success=True, data=data, metrics=metrics or Metrics())

    @classmethod
    def fail(cls, stage: str, reason: str, detail: str = "") -> "ApiResponse[None]":
        return cls(
            success=False,
            errors=[ErrorDetail(stage=stage, reason=reason, detail=detail)],
        )
