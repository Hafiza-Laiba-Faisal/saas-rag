"""Full-page renderer for PyMuPDF PDF pages."""

from __future__ import annotations

import numpy as np
import cv2
import fitz  # PyMuPDF


class PageRenderer:
    """Renders a PDF page as a raster image using PyMuPDF.

    This is the *scanned-page* fallback in the hybrid pipeline.  When a page
    has insufficient embedded text the pipeline calls :meth:`render` to
    produce a high-resolution bitmap that is then fed into the image
    preprocessor and OCR engine.
    """

    def render(self, page: fitz.Page, dpi: int) -> np.ndarray:
        """Render a PDF page to a numpy image array.

        The method uses PyMuPDF's ``page.get_pixmap(dpi=dpi)`` to rasterise
        the page at the requested resolution, then converts the resulting
        pixmap to a BGR numpy array via a PNG round-trip through OpenCV:

        1. ``pixmap.tobytes("png")`` — encode the pixmap as an in-memory PNG
           byte string.
        2. ``np.frombuffer(..., dtype=np.uint8)`` — wrap the bytes in a
           1-D numpy array without copying.
        3. ``cv2.imdecode(..., cv2.IMREAD_COLOR)`` — decode to a BGR
           ``HxWxC`` uint8 array.

        Args:
            page: A :class:`fitz.Page` from an open :class:`fitz.Document`.
            dpi: Resolution in dots-per-inch at which to render the page.
                Higher values produce larger, more detailed images.
                Typical values are 150 (fast) and 300 (high quality).

        Returns:
            A ``np.ndarray`` of shape ``(H, W, 3)`` with dtype ``uint8``
            representing the rendered page in BGR colour order.

        Raises:
            ValueError: If the pixmap could not be decoded by OpenCV.
        """
        pixmap: fitz.Pixmap = page.get_pixmap(dpi=dpi)
        png_bytes: bytes = pixmap.tobytes("png")
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(
                f"cv2.imdecode failed to decode the rendered page pixmap "
                f"(dpi={dpi}, pixmap size={len(png_bytes)} bytes)."
            )
        return image
