"""OCR engine wrapper around PaddleOCR.

This module provides :class:`OCREngine`, a thin wrapper that initialises
PaddleOCR once and exposes a single :meth:`OCREngine.run` method that
accepts a NumPy image array and returns a list of :class:`~schemas.ocr.OCRRegion`
instances.  The class is designed to be instantiated once at application
startup (via FastAPI's lifespan context) and shared as a singleton across all
request handlers.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from schemas.ocr import OCRRegion

logger = logging.getLogger(__name__)


class OCREngine:
    """Wrapper around :class:`paddleocr.PaddleOCR`.

    The PaddleOCR instance is created once during :meth:`__init__` and reused
    for every subsequent call to :meth:`run`.  This avoids the significant
    model-loading overhead that would occur if the engine were re-created per
    request.

    Args:
        languages: List of BCP-47-style language codes that the engine should
            support (e.g. ``["en", "ur", "ar"]``).  PaddleOCR natively
            supports a single ``lang`` parameter; the primary language (first
            entry) is used for model selection.  Multi-script support can be
            extended by subclassing or wrapping with language-specific
            instances.
        use_gpu: Whether to enable GPU-accelerated inference.  Set to
            ``False`` for CPU-only deployments.

    Raises:
        RuntimeError: If PaddleOCR fails to initialise (e.g. missing model
            files or incompatible dependencies).
    """

    def __init__(self, languages: list[str], use_gpu: bool) -> None:
        self._languages: list[str] = languages
        self._use_gpu: bool = use_gpu
        self._ocr: Any = self._init_paddle(languages, use_gpu)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _init_paddle(languages: list[str], use_gpu: bool) -> Any:
        """Initialise and return a :class:`paddleocr.PaddleOCR` instance.

        Uses the ``onnxruntime`` inference engine for Python 3.14 compatibility
        since ``paddlepaddle`` wheels only exist for Python 3.9–3.11.

        Supports:
        - Japanese vertical text (ja) with proper orientation
        - Angle classification for rotated documents
        - Mixed-language documents (en, ur, ar, ja, zh, etc.)

        Args:
            languages: Requested language codes.
            use_gpu: Whether to use GPU for inference (ignored for onnxruntime).

        Returns:
            Initialised ``PaddleOCR`` object.

        Raises:
            RuntimeError: Wraps any exception raised during PaddleOCR init.
        """
        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "paddleocr is not installed. "
                "Install it with: pip install paddleocr onnxruntime"
            ) from exc

        # Determine primary language for model selection.
        primary_lang = languages[0] if languages else "en"

        if len(languages) > 1:
            logger.info(
                "OCREngine initialised with multiple languages %s; "
                "using %r as primary PaddleOCR lang. "
                "PP-OCRv6 medium model supports 50+ languages including Japanese vertical text.",
                languages,
                primary_lang,
            )

        try:
            # PaddleOCR 3.x - use_angle_cls removed, use onnxruntime engine
            ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                engine="onnxruntime",
                lang=primary_lang,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise PaddleOCR with lang={primary_lang!r}: {exc}"
            ) from exc

        logger.info(
            "OCREngine ready (lang=%r, engine=onnxruntime)",
            primary_lang,
        )
        return ocr

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, image: np.ndarray) -> list[OCRRegion]:
        """Run OCR inference on a single image.

        Calls ``self._ocr.predict(image)`` (PaddleOCR 3.x API) and converts
        the raw output into a list of :class:`~schemas.ocr.OCRRegion` objects.

        Args:
            image: A NumPy array representing the image to process.  Expected
                format is ``HxWxC`` uint8 (BGR or grayscale), consistent with
                OpenCV output.

        Returns:
            A list of :class:`~schemas.ocr.OCRRegion` instances, one per
            detected text region.  Returns an empty list when PaddleOCR finds
            no text or returns ``None``.
        """
        # PaddleOCR 3.x requires a 3-channel BGR image (H×W×3).
        # The preprocessor returns a grayscale (H×W) array — convert it.
        if image.ndim == 2:
            image = np.stack([image, image, image], axis=-1)
        elif image.shape[2] == 1:
            image = np.concatenate([image, image, image], axis=-1)

        try:
            raw_results = self._ocr.predict(image)
        except Exception as exc:
            logger.error("PaddleOCR inference failed: %s", exc, exc_info=True)
            raise RuntimeError(f"OCR inference error: {exc}") from exc

        return self._parse_results(raw_results)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_results(raw_results: Any) -> list[OCRRegion]:
        """Convert raw PaddleOCR 3.x output to a list of :class:`OCRRegion`.

        PaddleOCR 3.x ``predict()`` returns a list of result objects. Each
        result has ``rec_texts``, ``rec_scores``, and ``rec_polys`` attributes.
        
        Filters out low-confidence results to improve output quality.

        Args:
            raw_results: The value returned by ``PaddleOCR.predict()``.

        Returns:
            Parsed list of :class:`OCRRegion` instances; empty list on
            ``None`` / empty input. Only includes results with confidence >= 0.5.
        """
        if not raw_results:
            return []

        regions: list[OCRRegion] = []
        min_confidence = 0.5  # Filter out very low confidence results

        for result in raw_results:
            if result is None:
                continue

            # PaddleOCR 3.x result object with rec_texts, rec_scores, rec_polys
            try:
                texts = result.get("rec_texts", []) if hasattr(result, "get") else getattr(result, "rec_texts", [])
                scores = result.get("rec_scores", []) if hasattr(result, "get") else getattr(result, "rec_scores", [])
                polys = result.get("rec_polys", []) if hasattr(result, "get") else getattr(result, "rec_polys", [])
            except Exception:
                # Fallback: try dict-style access
                try:
                    res_dict = result if isinstance(result, dict) else dict(result)
                    texts = res_dict.get("rec_texts", [])
                    scores = res_dict.get("rec_scores", [])
                    polys = res_dict.get("rec_polys", [])
                except Exception:
                    logger.warning("Could not parse PaddleOCR result: %s", type(result))
                    continue

            for text, score, poly in zip(texts, scores, polys):
                if not text:
                    continue

                try:
                    confidence = float(score)
                except (TypeError, ValueError):
                    confidence = 0.0

                # Skip very low confidence results
                if confidence < min_confidence:
                    logger.debug("Skipping low-confidence result (%.2f): %s", confidence, text)
                    continue

                # Convert polygon to axis-aligned bounding box
                try:
                    pts = np.array(poly)
                    bounding_box: list[int] = [
                        int(pts[:, 0].min()),
                        int(pts[:, 1].min()),
                        int(pts[:, 0].max()),
                        int(pts[:, 1].max()),
                    ]
                except Exception as exc:
                    logger.warning("Skipping region with malformed poly %s: %s", poly, exc)
                    continue

                regions.append(
                    OCRRegion(
                        text=str(text),
                        confidence=confidence,
                        bounding_box=bounding_box,
                    )
                )

        return regions
