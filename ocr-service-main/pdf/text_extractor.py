"""Embedded text extractor for PyMuPDF PDF pages."""

from __future__ import annotations

import fitz  # PyMuPDF


class EmbeddedTextExtractor:
    """Extracts embedded (digital) text from a PyMuPDF page.

    Uses PyMuPDF's ``page.get_text()`` method which returns the plain-text
    content already embedded in the PDF without any OCR inference.  This is
    the fast path in the hybrid pipeline: if the extracted text is long enough
    we can skip the expensive full-page render + OCR step.
    """

    def extract(self, page: fitz.Page) -> str:
        """Extract embedded text from a PyMuPDF page.

        Args:
            page: A :class:`fitz.Page` object obtained from an open
                :class:`fitz.Document`.

        Returns:
            The plain-text string embedded in the page, or an empty string
            if the page contains no extractable text.
        """
        try:
            text: str = page.get_text("text")
            return text if text else ""
        except Exception:
            return ""
