"""Embedded image extractor for PyMuPDF PDF pages."""

from __future__ import annotations

import numpy as np
import cv2
import fitz  # PyMuPDF


class EmbeddedImageExtractor:
    """Extracts embedded images from a PyMuPDF PDF page.

    Iterates over the XObject image references on a page, decodes each one
    from its raw bytes using OpenCV, and returns the results as a list of
    numpy arrays in BGR format.  Images that cannot be decoded are silently
    skipped so that a single corrupt embedded image does not abort processing
    of the entire page.
    """

    def extract(self, page: fitz.Page) -> list[np.ndarray]:
        """Extract all embedded images from a PDF page.

        For each image reference on the page the method:

        1. Reads the cross-reference number (*xref*) from
           ``page.get_images(full=True)``.
        2. Fetches the raw image bytes via ``page.parent.extract_image(xref)``, which
           returns a dict with ``"image"`` (``bytes``) and ``"ext"``
           (file-extension string such as ``"png"`` or ``"jpeg"``).
        3. Decodes the bytes into a numpy array with
           ``cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)``.
        4. Skips any image for which ``cv2.imdecode`` returns ``None``.

        Args:
            page: A :class:`fitz.Page` from an open :class:`fitz.Document`.

        Returns:
            A list of ``np.ndarray`` objects in BGR uint8 format, one per
            successfully decoded embedded image.  Returns an empty list if
            the page contains no images or none could be decoded.
        """
        images: list[np.ndarray] = []

        try:
            image_list = page.get_images(full=True)
        except Exception:
            return images

        for img_info in image_list:
            xref: int = img_info[0]  # first element is always the xref
            try:
                # Use page.parent to access the parent document
                doc = page.parent
                img_data = doc.extract_image(xref)
                img_bytes: bytes = img_data["image"]
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if decoded is not None:
                    images.append(decoded)
            except Exception:
                # Skip images that cannot be extracted or decoded
                continue

        return images
