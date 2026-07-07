"""OCR Data Schemas"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path


@dataclass
class OCRRegion:
    """A text region detected by OCR."""
    text: str
    confidence: float
    bounding_box: list[int]  # [x0, y0, x1, y1]
    page_number: int = 1


@dataclass
class OCRPage:
    """A single page OCR result."""
    page_number: int
    regions: list[OCRRegion]
    full_text: str
    words: list[str]
    confidence: float = 0.0

    def __post_init__(self):
        if not self.confidence and self.regions:
            confs = [r.confidence for r in self.regions if r.confidence > 0]
            self.confidence = sum(confs) / len(confs) if confs else 0.0


@dataclass
class OCRResult:
    """Complete OCR result for a document."""
    filename: str
    pages: list[OCRPage]
    processing_time_ms: float
    engine: str
    error: str | None = None
    preprocessing_applied: list[str] = field(default_factory=list)

    @property
    def total_text(self) -> str:
        return "\n\n".join(page.full_text for page in self.pages)

    @property
    def total_words(self) -> int:
        return sum(len(page.words) for page in self.pages)

    @property
    def avg_confidence(self) -> float:
        if not self.pages:
            return 0.0
        return sum(page.confidence for page in self.pages) / len(self.pages)