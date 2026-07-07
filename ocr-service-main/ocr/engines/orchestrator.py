"""OCR Engine Orchestrator — routes to primary engine with automatic fallback."""
from __future__ import annotations

import logging
from typing import List

from ocr.engines.base import BaseOCREngine
from schemas.ocr import PageResult

logger = logging.getLogger(__name__)


class OCROrchestrator:
    """Manages multiple OCR engines and provides automatic fallback.

    Usage:
        orchestrator = OCROrchestrator([mistral_engine, paddle_engine])
        result = orchestrator.process_image(data, "file.png")
        # Tries mistral first; if it fails, falls back to paddle.
    """

    def __init__(self, engines: List[BaseOCREngine]) -> None:
        self._engines = [e for e in engines if e.is_available()]
        if not self._engines:
            logger.warning("No OCR engines are available!")
        else:
            names = [type(e).__name__ for e in self._engines]
            logger.info("OCROrchestrator ready with engines: %s", names)

    @property
    def available_engines(self) -> List[str]:
        return [type(e).__name__ for e in self._engines]

    def process_image(self, image_data: bytes, filename: str) -> PageResult:
        """Try each engine in order until one succeeds."""
        last_error = None
        for engine in self._engines:
            try:
                logger.info("Trying %s for image: %s", type(engine).__name__, filename)
                result = engine.process_image(image_data, filename)
                logger.info("Success with %s for %s", type(engine).__name__, filename)
                return result
            except Exception as e:
                logger.warning("%s failed for %s: %s", type(engine).__name__, filename, e)
                last_error = e
                continue

        raise RuntimeError(
            f"All OCR engines failed for {filename}. Last error: {last_error}"
        )

    def process_pdf(self, pdf_bytes: bytes, filename: str) -> List[PageResult]:
        """Try each engine in order until one succeeds."""
        last_error = None
        for engine in self._engines:
            try:
                logger.info("Trying %s for PDF: %s", type(engine).__name__, filename)
                result = engine.process_pdf(pdf_bytes, filename)
                logger.info("Success with %s for %s", type(engine).__name__, filename)
                return result
            except Exception as e:
                logger.warning("%s failed for %s: %s", type(engine).__name__, filename, e)
                last_error = e
                continue

        raise RuntimeError(
            f"All OCR engines failed for {filename}. Last error: {last_error}"
        )
