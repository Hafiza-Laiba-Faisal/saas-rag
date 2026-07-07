"""Heuristic filter for identifying decorative (non-content) images."""

from __future__ import annotations

import math

import numpy as np
import cv2


class DecorativeImageFilter:
    """Classifies embedded PDF images as decorative or content-bearing.

    Logos, icons, horizontal rules, and other decorative elements waste OCR
    inference time without contributing meaningful text.  This filter uses
    two fast heuristics to skip such images:

    1. **Size check** — images smaller than :attr:`MIN_SIZE` pixels in either
       dimension are almost certainly icons or ornamental elements.
    2. **Entropy check** — images with a Shannon entropy (over the grayscale
       pixel histogram) below :attr:`MIN_ENTROPY_THRESHOLD` are likely solid
       colour fills, gradients, or very simple shapes with no readable text.

    Both checks are O(n) in the number of pixels and add negligible overhead
    compared with the OCR inference they prevent.
    """

    #: Minimum width *and* height (in pixels) for a non-decorative image.
    MIN_SIZE: int = 30

    #: Minimum Shannon entropy value; images below this are considered
    #: decorative (solid / near-uniform appearance).
    #: Lowered from 3.0 → 1.5 so invoice images / charts with text are not skipped.
    MIN_ENTROPY_THRESHOLD: float = 1.5

    def is_decorative(self, image: np.ndarray) -> bool:
        """Return ``True`` if the image is likely decorative.

        The method applies heuristics in the following order:

        1. If either image dimension is less than :attr:`MIN_SIZE` pixels
           → **decorative**.
        2. Compute the Shannon entropy of the grayscale histogram using
           ``cv2.calcHist``::

               gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)  # if needed
               hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
               hist /= hist.sum()
               entropy = -sum(p * log2(p) for p in hist.flatten() if p > 0)

           If ``entropy < MIN_ENTROPY_THRESHOLD`` → **decorative**.
        3. Otherwise → **not decorative** (treat as content image).

        Args:
            image: A numpy array of shape ``(H, W)`` or ``(H, W, C)``
                in uint8 format.

        Returns:
            ``True`` if the image should be skipped (decorative),
            ``False`` if the image should be passed to the OCR engine.
        """
        # ------------------------------------------------------------------
        # Heuristic 1: size check
        # ------------------------------------------------------------------
        h, w = image.shape[:2]
        if h < self.MIN_SIZE or w < self.MIN_SIZE:
            return True

        # ------------------------------------------------------------------
        # Heuristic 2: entropy check
        # ------------------------------------------------------------------
        # Convert to grayscale if the image has colour channels
        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        total: float = float(hist.sum())
        if total == 0:
            # Empty histogram → treat as decorative
            return True

        # Normalise and compute Shannon entropy
        entropy: float = 0.0
        for count in hist.flatten():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        if entropy < self.MIN_ENTROPY_THRESHOLD:
            return True

        return False
