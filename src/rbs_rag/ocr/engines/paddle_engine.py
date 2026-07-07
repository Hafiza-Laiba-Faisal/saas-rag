"""PaddleOCR Engine Implementation"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rbs_rag.ocr.engines.base import BaseOCREngine

logger = logging.getLogger(__name__)


class PaddleOCREngine(BaseOCREngine):
    """PaddleOCR engine for local OCR processing."""

    def __init__(self, languages: list[str] = None, use_gpu: bool = False):
        self.languages = languages or ["en"]
        self.use_gpu = use_gpu
        self._ocr = None
        self._initialized = False

    @property
    def name(self) -> str:
        return "PaddleOCR"

    def _init_engine(self):
        """Lazy initialization of PaddleOCR."""
        if self._initialized:
            return

        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang=",".join(self.languages),
                use_gpu=self.use_gpu,
                show_log=False,
                use_angle_cls=True,
            )
            self._initialized = True
            logger.info("PaddleOCR initialized with languages: %s", self.languages)
        except ImportError as e:
            logger.warning("PaddleOCR not available: %s", e)
            self._initialized = False
            self._ocr = None
        except Exception as e:
            logger.error("Failed to initialize PaddleOCR: %s", e)
            self._initialized = False
            self._ocr = None

    def is_available(self) -> bool:
        """Check if PaddleOCR is available."""
        if not self._initialized:
            self._init_engine()
        return self._ocr is not None

    def extract_text(self, image_path: Path) -> dict[str, Any]:
        """Extract text from an image file."""
        if not self.is_available():
            return {"text": "", "regions": [], "words": [], "error": "Engine not available"}

        try:
            result = self._ocr.ocr(str(image_path))
            return self._parse_result(result)
        except Exception as e:
            logger.error("PaddleOCR extraction failed: %s", e)
            return {"text": "", "regions": [], "words": [], "error": str(e)}

    def extract_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """Extract text from image bytes."""
        if not self.is_available():
            return {"text": "", "regions": [], "words": [], "error": "Engine not available"}

        try:
            import numpy as np
            import cv2
            arr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            result = self._ocr.ocr(img)
            return self._parse_result(result)
        except Exception as e:
            logger.error("PaddleOCR extraction from bytes failed: %s", e)
            return {"text": "", "regions": [], "words": [], "error": str(e)}

    def _parse_result(self, result: list) -> dict[str, Any]:
        """Parse PaddleOCR result into standardized format."""
        regions = []
        words = []
        full_text_parts = []

        if not result or not result[0]:
            return {"text": "", "regions": [], "words": []}

        for line in result[0]:
            if not line:
                continue
            bbox = line[0]
            text_info = line[1]
            text = text_info[0]
            confidence = text_info[1]

            # Convert bbox to [x0, y0, x1, y1] format
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x0, y0 = min(xs), min(ys)
            x1, y1 = max(xs), max(ys)

            regions.append({
                "text": text,
                "confidence": confidence,
                "bounding_box": [x0, y0, x1, y1],
            })
            words.append(text)
            full_text_parts.append(text)

        return {
            "text": "\n".join(full_text_parts),
            "regions": regions,
            "words": words,
        }