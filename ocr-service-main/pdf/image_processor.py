"""Extract, process, and OCR images from PDFs."""

from __future__ import annotations

import io
import logging
from typing import Any

import cv2
import fitz
import numpy as np

logger = logging.getLogger(__name__)


class PDFImageProcessor:
    """Extract images from PDF pages, filter, and prepare for OCR."""

    def __init__(self, preprocessor: Any, ocr_engine: Any) -> None:
        """Initialize with preprocessor and OCR engine.

        Args:
            preprocessor: ImagePreprocessor instance
            ocr_engine: OCREngine instance
        """
        self._preprocessor = preprocessor
        self._ocr_engine = ocr_engine

    def extract_and_process_images(self, page: Any, doc: Any) -> dict:
        """Extract all images from a PDF page and prepare results.

        Args:
            page: fitz.Page object
            doc: fitz.Document object

        Returns:
            Dict with:
            - images: List of extracted image arrays
            - image_ocr_results: OCR results for each image
            - image_info: Metadata about each image
        """
        result = {
            "images": [],
            "image_ocr_results": [],
            "image_info": [],
        }

        try:
            # Get all images in the page
            image_list = page.get_images(full=True)
            if not image_list:
                return result

            for img_index, img_ref in enumerate(image_list):
                try:
                    # Extract image from PDF
                    xref = img_ref[0]
                    pix = fitz.Pixmap(doc, xref)

                    # Convert to OpenCV format
                    if pix.n - pix.alpha < 4:  # GRAY or RGB
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                            (pix.height, pix.width, pix.n)
                        )
                        if pix.n == 1:  # Grayscale
                            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
                        else:  # RGB
                            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                    else:  # RGBA
                        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                            (pix.height, pix.width, pix.n)
                        )
                        img_bgr = cv2.cvtColor(img_array[:, :, :3], cv2.COLOR_RGB2BGR)

                    # Filter out small/decorative images (< 50x50)
                    h, w = img_bgr.shape[:2]
                    if h < 50 or w < 50:
                        continue

                    # Store image
                    result["images"].append(img_bgr)
                    result["image_info"].append({
                        "index": img_index,
                        "width": w,
                        "height": h,
                        "size_bytes": pix.n * w * h,
                    })

                    # Run OCR on image with preprocessing
                    try:
                        preprocessed = self._preprocessor.process(img_bgr)
                        img_for_ocr = cv2.cvtColor(preprocessed, cv2.COLOR_GRAY2BGR)
                        ocr_result = self._ocr_engine.run(img_for_ocr)
                        result["image_ocr_results"].append(ocr_result)
                    except Exception as e:
                        logger.warning("OCR failed for image %d: %s", img_index, e)
                        result["image_ocr_results"].append([])

                    pix = None  # Free memory

                except Exception as e:
                    logger.warning("Failed to extract image %d: %s", img_index, e)
                    continue

        except Exception as e:
            logger.warning("Image extraction failed: %s", e)

        return result

    @staticmethod
    def filter_content_images(images: list[np.ndarray]) -> list[np.ndarray]:
        """Filter out decorative/small images, keep content images.

        Args:
            images: List of image arrays

        Returns:
            Filtered list of content images
        """
        filtered = []
        for img in images:
            h, w = img.shape[:2]
            # Keep images > 100x100
            if h > 100 and w > 100:
                # Check if it's mostly non-white (content)
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                dark_pixels = np.sum(gray < 200)
                total_pixels = h * w
                if dark_pixels / total_pixels > 0.1:  # > 10% dark pixels
                    filtered.append(img)
        return filtered
