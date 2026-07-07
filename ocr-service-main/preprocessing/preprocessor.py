"""Image preprocessing pipeline for the OCR service."""
from __future__ import annotations

import cv2
import numpy as np

from config.settings import Settings, get_settings

# Hard cap — no image dimension will exceed this after preprocessing
MAX_SIDE = 2000


class ImagePreprocessor:
    """Applies a lightweight preprocessing chain before OCR inference.

    Steps (in order):
        1. Cap size — resize so longest side ≤ MAX_SIDE (saves RAM)
        2. Grayscale
        3. Upscale small images (shortest side < 800px) up to MAX_SIDE
        4. CLAHE contrast enhancement
        5. Adaptive threshold (binarise)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def process(self, image: np.ndarray) -> np.ndarray:
        """Run the preprocessing pipeline and return a grayscale image."""
        image = self._cap_size(image)
        # PaddleOCR works best with natural images; aggressive binarization harms accuracy
        # so we only resize and grayscale here.
        image = self._to_grayscale(image)
        image = self._upscale_small(image)
        return image

    # ── steps ────────────────────────────────────────────────────────

    @staticmethod
    def _cap_size(image: np.ndarray) -> np.ndarray:
        """Downscale so the longest side is ≤ MAX_SIDE."""
        h, w = image.shape[:2]
        longest = max(h, w)
        if longest > MAX_SIDE:
            scale = MAX_SIDE / longest
            image = cv2.resize(
                image,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        return image

    @staticmethod
    def _to_grayscale(image: np.ndarray) -> np.ndarray:
        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image

    @staticmethod
    def _upscale_small(image: np.ndarray) -> np.ndarray:
        """Upscale if shortest side < 800px — improves OCR on small images."""
        h, w = image.shape[:2]
        shortest = min(h, w)
        if shortest < 800:
            scale = min(800 / shortest, MAX_SIDE / max(h, w))
            if scale > 1.0:
                image = cv2.resize(
                    image,
                    (int(w * scale), int(h * scale)),
                    interpolation=cv2.INTER_CUBIC,
                )
        return image

    @staticmethod
    def _enhance_contrast(image: np.ndarray) -> np.ndarray:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(image)

    @staticmethod
    def _adaptive_threshold(image: np.ndarray) -> np.ndarray:
        return cv2.adaptiveThreshold(
            image, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )

    # ── keep process_advanced for any callers that use it ────────────

    def process_advanced(self, image: np.ndarray, **_kwargs) -> np.ndarray:
        """Same as process() — advanced flags ignored (simplified pipeline)."""
        return self.process(image)

    # ── auto_rotate kept for advanced.py endpoint ────────────────────

    def _auto_rotate(self, image: np.ndarray) -> np.ndarray:
        """Deskew image using minAreaRect on contours."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return image
        all_points = np.concatenate(contours, axis=0)
        angle: float = cv2.minAreaRect(all_points)[2]
        if angle < -45.0:
            angle += 90.0
        elif angle > 45.0:
            angle -= 90.0
        h, w = image.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
        return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
