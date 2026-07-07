"""PDF Processing Pipeline"""
from __future__ import annotations

import fitz  # PyMuPDF
from pathlib import Path
from typing import Any


class PDFProcessor:
    """Process PDF files - extract text or render pages as images."""

    def __init__(self, dpi: int = 150):
        self.dpi = dpi

    def extract_text(self, pdf_path: Path) -> list[dict[str, Any]]:
        """Extract text from each page of a PDF."""
        pages = []
        
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            
            pages.append({
                "page_number": page_num + 1,
                "text": text,
                "regions": [],
                "words": text.split() if text else [],
                "word_count": len(text.split()) if text else 0,
                "confidence": 1.0 if text.strip() else 0.0,
            })
        
        doc.close()
        return pages

    def render_pages(self, pdf_path: Path, dpi: int = None) -> list[bytes]:
        """Render PDF pages as PNG images."""
        dpi = dpi or self.dpi
        images = []
        
        doc = fitz.open(str(pdf_path))
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            images.append(img_bytes)
        
        doc.close()
        return images

    def is_scanned(self, pdf_path: Path, min_text_chars: int = 20) -> bool:
        """Check if a PDF is scanned (has little extractable text)."""
        doc = fitz.open(str(pdf_path))
        total_chars = 0
        
        for page in doc:
            text = page.get_text("text")
            total_chars += len(text.strip())
        
        doc.close()
        return total_chars < min_text_chars * len(doc)