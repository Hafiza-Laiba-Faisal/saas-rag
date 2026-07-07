from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseOCREngine(ABC):
    """Base class for OCR engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine name."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if engine is available."""
        pass

    @abstractmethod
    def extract_text(self, image_path: Path) -> dict[str, Any]:
        """Extract text from image file."""
        pass

    @abstractmethod
    def extract_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """Extract text from image bytes."""
        pass