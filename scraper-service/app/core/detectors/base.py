"""
Base detector interface.
Detectors ONLY detect conditions — they never attempt bypasses.
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class BaseDetector(ABC):
    """Detects a specific page condition from HTML source."""

    @abstractmethod
    def detect(self, html: str, url: str = "") -> bool:
        """Return True if condition is detected."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable detector name."""
        ...
