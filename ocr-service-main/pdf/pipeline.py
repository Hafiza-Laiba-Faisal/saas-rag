"""Hybrid PDF processing pipeline combining embedded text and OCR.

This module provides :class:`HybridPDFPipeline`, which implements a four-step
per-page strategy:

  1. Extract embedded (digital) text via PyMuPDF.
  2. Extract embedded images, filter decorative ones, and run OCR on each.
  3. Merge embedded text with image OCR results.
  4. If embedded text is below the configured threshold, render the full page
     and run OCR on the rasterised result instead.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import fitz  # PyMuPDF

from config.settings import Settings
from ocr.engine import OCREngine
from pdf.decorative_filter import DecorativeImageFilter
from pdf.image_extractor import EmbeddedImageExtractor
from pdf.page_renderer import PageRenderer
from pdf.text_extractor import EmbeddedTextExtractor
from postprocessing.extractor import EntityExtractor
from preprocessing.preprocessor import ImagePreprocessor
from schemas.ocr import PageResult
from services.result_builder import ResultBuilder
from utils.logger import get_logger

logger = get_logger(__name__)


class HybridPDFPipeline:
    """Four-step hybrid pipeline for PDF text extraction.

    Steps per page:
      1. Extract embedded text (PyMuPDF).
      2. Extract embedded images, filter decorative, run OCR on each.
      3. Merge embedded text + image OCR results.
      4. If embedded text < threshold → render full page + OCR instead.

    Args:
        ocr_engine: Initialised :class:`~ocr.engine.OCREngine` instance used
            for inference on image arrays.
        preprocessor: :class:`~preprocessing.preprocessor.ImagePreprocessor`
            instance that applies the OpenCV preprocessing chain before OCR.
        entity_extractor: :class:`~postprocessing.extractor.EntityExtractor`
            used to extract URLs, emails, and phone numbers from final text.
        result_builder: :class:`~services.result_builder.ResultBuilder` used
            to assemble :class:`~schemas.ocr.PageResult` objects.
        settings: Application :class:`~config.settings.Settings` providing
            ``min_text_chars_threshold`` and ``page_render_dpi``.
    """

    def __init__(
        self,
        ocr_engine: OCREngine,
        preprocessor: ImagePreprocessor,
        entity_extractor: EntityExtractor,
        result_builder: ResultBuilder,
        settings: Settings,
    ) -> None:
        self._ocr_engine = ocr_engine
        self._preprocessor = preprocessor
        self._entity_extractor = entity_extractor
        self._result_builder = result_builder
        self._settings = settings

        # Component helpers — stateless, so class-level instances are fine.
        self._text_extractor = EmbeddedTextExtractor()
        self._image_extractor = EmbeddedImageExtractor()
        self._page_renderer = PageRenderer()
        self._decorative_filter = DecorativeImageFilter()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process(self, pdf_path: Path) -> list[PageResult]:
        """Open *pdf_path* and process each page through the hybrid pipeline.

        Args:
            pdf_path: Path to the PDF file to process.

        Returns:
            A list of :class:`~schemas.ocr.PageResult` objects, one per page,
            in document order.
        """
        results: list[PageResult] = []

        doc: fitz.Document = fitz.open(str(pdf_path))
        try:
            for page_num, page in enumerate(doc, start=1):
                page_result = self._process_page(page, doc, page_num)
                results.append(page_result)
        finally:
            doc.close()

        logger.info("Processed %d page(s) from %s", len(results), pdf_path.name)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_page(
        self, page: fitz.Page, doc: fitz.Document, page_num: int
    ) -> PageResult:
        """Process a single PDF page.

        Strategy:
          1. Extract embedded (digital) text via PyMuPDF.
          2. Check for embedded images.
          3. If the page has ANY embedded images, or if the digital text length
             is below the threshold, render the FULL page and run OCR. This ensures
             text from both the PDF layer and images are extracted in perfect
             reading order (avoiding 'messy' concatenated output).
          4. Memory is explicitly cleaned up to prevent OOM errors.
        """
        # ── Step 1: embedded digital text ────────────────────────────────
        embedded_text: str = self._text_extractor.extract(page)
        logger.debug("Page %d: embedded text = %d chars", page_num, len(embedded_text))

        # ── Step 2: Extract embedded images ─────────────────────────────
        images = []
        try:
            images = self._image_extractor.extract(page)
            logger.debug("Page %d: %d embedded image(s) found", page_num, len(images))
        except Exception as exc:
            logger.warning("Page %d: image extraction failed: %s", page_num, exc)

        threshold = self._settings.min_text_chars_threshold

        # ── Step 3: Full-page render fallback if images present or text < threshold ──
        if images or len(embedded_text.strip()) < threshold:
            logger.debug(
                "Page %d: has images (%d) or text < threshold (%d) → full-page render OCR",
                page_num, len(images), threshold,
            )
            try:
                rendered = self._page_renderer.render(page, self._settings.page_render_dpi)
                try:
                    preprocessed = self._preprocessor.process(rendered)
                    img_bgr = cv2.cvtColor(preprocessed, cv2.COLOR_GRAY2BGR)
                    del preprocessed  # memory cleanup
                except Exception:
                    img_bgr = rendered

                del rendered  # memory cleanup

                scanned_regions = self._ocr_engine.run(img_bgr)
                del img_bgr  # memory cleanup

                if scanned_regions:
                    # Full-page OCR replaces everything — it already contains all text + images in reading order
                    full_text = "\n".join(r.text for r in scanned_regions)
                    entities = self._entity_extractor.extract(full_text)
                    return self._result_builder.build_page_result(
                        page_num, scanned_regions, entities, ""
                    )
            except Exception as exc:
                logger.error("Page %d: full-page render OCR failed: %s", page_num, exc)

        # ── Step 4: Normal path (no images, mostly digital text) ─────────
        entities = self._entity_extractor.extract(embedded_text)
        return self._result_builder.build_page_result(
            page_num, [], entities, embedded_text
        )
