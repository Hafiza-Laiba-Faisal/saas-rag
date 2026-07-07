"""PDF OCR service using the pluggable OCR orchestrator."""
from __future__ import annotations

import time

from ocr.engines.orchestrator import OCROrchestrator
from postprocessing.extractor import EntityExtractor
from schemas.ocr import OCRResult
from services.result_builder import ResultBuilder
from utils.logger import get_logger

logger = get_logger(__name__)


class PDFOCRService:
    """Service that accepts raw PDF bytes, runs through the orchestrator, and returns an OCRResult."""

    def __init__(self, orchestrator: OCROrchestrator, result_builder: ResultBuilder) -> None:
        self._orchestrator = orchestrator
        self._result_builder = result_builder
        self._entity_extractor = EntityExtractor()

    def process(self, pdf_data: bytes, filename: str, request_id: str) -> OCRResult:
        """Process PDF bytes through the orchestrator.

        Args:
            pdf_data: Raw PDF bytes to process.
            filename: Original filename reported in the result.
            request_id: Unique identifier for this request.

        Returns:
            A fully populated OCRResult.
        """
        start = time.monotonic()

        pages = self._orchestrator.process_pdf(pdf_data, filename)

        # Extract entities for each page
        for page in pages:
            if page.full_text and not page.entities.urls and not page.entities.emails:
                page.entities = self._entity_extractor.extract(page.full_text)

        processing_time_ms = (time.monotonic() - start) * 1000

        logger.info(
            "PDFOCRService processed %s in %.1f ms (request_id=%s)",
            filename,
            processing_time_ms,
            request_id,
        )

        return self._result_builder.build_ocr_result(
            request_id, filename, pages, processing_time_ms, processing_time_ms
        )
