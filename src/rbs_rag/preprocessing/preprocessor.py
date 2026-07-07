"""Image Preprocessing for OCR"""
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from typing import Optional
import tempfile
import os


class ImagePreprocessor:
    """Preprocess images to improve OCR accuracy."""

    def __init__(self):
        pass

    def preprocess(self, image_path: Path) -> Path:
        """Apply preprocessing pipeline and return path to processed image."""
        # Read image
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        # Apply preprocessing steps
        img = self._auto_rotate(img)
        img = self._enhance_contrast(img)
        img = self._denoise(img)
        img = self._upscale_if_needed(img)

        # Save processed image to temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            cv2.imwrite(tmp.name, img)
            return Path(tmp.name)

    def _auto_rotate(self, img: np.ndarray) -> np.ndarray:
        """Detect and correct rotation using minAreaRect on text contours."""
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return img
            
            # Get largest contour
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) < 100:
                return img
            
            # Get minimum area rectangle
            rect = cv2.minAreaRect(largest)
            angle = rect[-1]
            
            # Correct angle
            if angle < -45:
                angle += 90
            
            if abs(angle) > 0.5:
                h, w = img.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        except Exception:
            pass  # If rotation detection fails, return original
        
        return img

    def _enhance_contrast(self, img: np.ndarray) -> np.ndarray:
        """Enhance contrast using CLAHE."""
        if len(img.shape) == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            lab = cv2.merge((l, a, b))
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(img)

    def _denoise(self, img: np.ndarray) -> np.ndarray:
        """Remove noise from image."""
        if len(img.shape) == 3:
            return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
        else:
            return cv2.fastNlMeansDenoising(img, None, 10, 7, 21)

    def _upscale_if_needed(self, img: np.ndarray, min_dim: int = 1000) -> np.ndarray:
        """Upscale image if dimensions are too small."""
        h, w = img.shape[:2]
        if max(h, w) < min_dim:
            scale = min_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return img