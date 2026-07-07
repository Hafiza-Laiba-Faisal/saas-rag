"""Image OCR service using the pluggable OCR orchestrator."""
from __future__ import annotations

import time

from ocr.engines.orchestrator import OCROrchestrator
from postprocessing.extractor import EntityExtractor
from schemas.ocr import OCRResult
from services.result_builder import ResultBuilder
from utils.logger import get_logger

logger = get_logger(__name__)


class ImageOCRService:
    """Orchestrates the full image OCR pipeline via the OCROrchestrator."""

    def __init__(self, orchestrator: OCROrchestrator, result_builder: ResultBuilder) -> None:
        self._orchestrator = orchestrator
        self._result_builder = result_builder
        self._entity_extractor = EntityExtractor()

    def process(self, image_data: bytes, filename: str, request_id: str) -> OCRResult:
        """Process raw image bytes through the orchestrator.

        Args:
            image_data: Raw image bytes
            filename: Original filename
            request_id: Unique request ID

        Returns:
            OCRResult with extracted text
        """
        start = time.monotonic()

        page = self._orchestrator.process_image(image_data, filename)

        # Extract entities from full text
        if page.full_text and not page.entities.urls and not page.entities.emails:
            page.entities = self._entity_extractor.extract(page.full_text)

        processing_time_ms = (time.monotonic() - start) * 1000

        logger.info(
            "Processed %s in %.1f ms",
            filename,
            processing_time_ms,
            extra={"request_id": request_id},
        )

        return self._result_builder.build_ocr_result(
            request_id, filename, [page], processing_time_ms, processing_time_ms
        )
