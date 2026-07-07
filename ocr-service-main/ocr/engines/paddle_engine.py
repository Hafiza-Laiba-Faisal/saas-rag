"""PaddleOCR engine implementation (local/fallback)."""
from __future__ import annotations

import logging
import time
from typing import List

import cv2
import numpy as np

from ocr.engines.base import BaseOCREngine
from preprocessing.preprocessor import ImagePreprocessor
from postprocessing.extractor import EntityExtractor
from services.result_builder import ResultBuilder
from schemas.ocr import PageResult, OCRRegion

logger = logging.getLogger(__name__)


class PaddleOCREngine(BaseOCREngine):
    """Wraps PaddleOCR as a BaseOCREngine for the orchestrator."""

    def __init__(self, languages: list[str], use_gpu: bool) -> None:
        self._languages = languages
        self._use_gpu = use_gpu
        self._ocr = None
        self._preprocessor = ImagePreprocessor()
        self._entity_extractor = EntityExtractor()
        self._result_builder = ResultBuilder()
        try:
            from ocr.engine import OCREngine
            self._paddle = OCREngine(languages=languages, use_gpu=use_gpu)
            logger.info("PaddleOCREngine initialized successfully")
        except Exception as e:
            logger.warning("PaddleOCREngine could not initialize: %s", e)
            self._paddle = None

    def is_available(self) -> bool:
        return self._paddle is not None

    def process_image(self, image_data: bytes, filename: str) -> PageResult:
        """Process image bytes through PaddleOCR."""
        arr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Failed to decode image: {filename}")

        try:
            preprocessed = self._preprocessor.process(image)
            image_for_ocr = cv2.cvtColor(preprocessed, cv2.COLOR_GRAY2BGR)
        except Exception as e:
            logger.warning("Preprocessing failed, using original: %s", e)
            image_for_ocr = image

        regions = self._paddle.run(image_for_ocr)
        full_text = "\n".join(r.text for r in regions)
        entities = self._entity_extractor.extract(full_text)
        return self._result_builder.build_page_result(1, regions, entities)

    def process_pdf(self, pdf_bytes: bytes, filename: str) -> List[PageResult]:
        """Process PDF through the existing HybridPDFPipeline."""
        import os
        import tempfile
        from pathlib import Path
        from config.settings import get_settings
        from pdf.pipeline import HybridPDFPipeline

        settings = get_settings()
        pipeline = HybridPDFPipeline(
            self._paddle, self._preprocessor,
            self._entity_extractor, self._result_builder, settings
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)

        try:
            pages = pipeline.process(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return pages
