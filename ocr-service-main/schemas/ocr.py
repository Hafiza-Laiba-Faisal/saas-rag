"""Pydantic models for OCR data structures."""

from __future__ import annotations

from typing import Union

from pydantic import BaseModel, Field


class OCRRegion(BaseModel):
    """A single detected text region with its bounding box and confidence score."""

    text: str = Field(..., description="Recognized text in this region")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="OCR confidence score 0-1"
    )
    bounding_box: list[int] = Field(
        ..., description="[x_min, y_min, x_max, y_max]"
    )


class ExtractedEntities(BaseModel):
    """Entities extracted from OCR text via regex."""

    urls: list[str] = Field(default_factory=list, description="Extracted URLs")
    emails: list[str] = Field(
        default_factory=list, description="Extracted email addresses"
    )
    phone_numbers: list[str] = Field(
        default_factory=list, description="Extracted phone numbers"
    )


class PageResult(BaseModel):
    """OCR result for a single page."""

    page_number: int = Field(..., ge=1, description="1-indexed page number")
    full_text: str = Field(..., description="Full extracted text for this page")
    markdown: Union[str, None] = Field(None, description="Formatted markdown text (Mistral)")
    tables: list[str] = Field(default_factory=list, description="Extracted tables in HTML/Markdown format (Mistral)")
    hyperlinks: list[str] = Field(default_factory=list, description="Extracted hyperlinks (Mistral)")
    paragraphs: list[str] = Field(
        default_factory=list, description="Text split by paragraphs"
    )
    lines: list[str] = Field(
        default_factory=list, description="Text split by lines"
    )
    words: list[str] = Field(
        default_factory=list, description="All words on the page"
    )
    regions: list[OCRRegion] = Field(
        default_factory=list, description="OCR detected regions"
    )
    entities: ExtractedEntities = Field(
        default_factory=ExtractedEntities,
        description="Extracted entities",
    )


class OCRResult(BaseModel):
    """Complete OCR result for a single file."""

    request_id: str = Field(..., description="Unique request identifier")
    filename: str = Field(..., description="Original filename")
    pages: list[PageResult] = Field(..., description="Per-page OCR results")
    processing_time_ms: float = Field(
        ..., ge=0, description="Total processing time in ms"
    )
    ocr_duration_ms: float = Field(
        ..., ge=0, description="OCR inference time in ms"
    )


class FileErrorResult(BaseModel):
    """Error record for a single file that failed processing in a batch."""

    filename: str = Field(..., description="Filename that failed")
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Machine-readable error code")


class BatchResult(BaseModel):
    """Aggregated result for a batch processing request."""

    request_id: str = Field(..., description="Unique request identifier")
    results: list[Union[OCRResult, FileErrorResult]] = Field(
        ..., description="Per-file results"
    )
    total_files: int = Field(..., ge=0, description="Total files submitted")
    successful: int = Field(..., ge=0, description="Successfully processed files")
    failed: int = Field(..., ge=0, description="Failed files")
