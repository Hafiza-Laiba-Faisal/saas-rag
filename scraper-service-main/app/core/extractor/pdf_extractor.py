"""
PDF text extraction with OCR fallback for scanned documents.
"""
from __future__ import annotations
from pathlib import Path
import tempfile
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdfdocument import PDFDocument
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False

try:
    from pdf2image import convert_from_path
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


class PDFExtractor:
    """
    Extract text from PDF files.
    
    Strategies:
    1. Direct text extraction (pdfminer.six) — fast, works for text-based PDFs
    2. OCR extraction (pytesseract) — slow, works for scanned PDFs
    """

    def __init__(self, use_ocr: bool = False):
        """
        Initialize PDF extractor.
        
        Args:
            use_ocr: Enable OCR for scanned PDFs (requires pytesseract + pdf2image)
        """
        self.use_ocr = use_ocr and HAS_OCR

        if not HAS_PDFMINER:
            raise ImportError("pdfminer.six not installed. Run: pip install pdfminer.six")

    def extract_text(self, pdf_path: str | Path) -> dict:
        """
        Extract text from PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            {
                "text": str,
                "pages": int,
                "method": "direct" | "ocr",
                "metadata": dict
            }
        """
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Try direct extraction first
        result = self._extract_direct(pdf_path)
        
        # If no text found and OCR enabled, try OCR
        if not result["text"].strip() and self.use_ocr:
            result = self._extract_ocr(pdf_path)
        
        return result

    def _extract_direct(self, pdf_path: Path) -> dict:
        """Extract text directly from PDF using pdfminer.six."""
        text = ""
        try:
            text = pdfminer_extract_text(str(pdf_path))
        except Exception as e:
            logger.error(f"pdfminer text extraction failed: {e}")

        metadata = {}
        pages_count = 0
        try:
            with open(pdf_path, "rb") as fp:
                parser = PDFParser(fp)
                doc = PDFDocument(parser)
                if doc.info:
                    for info in doc.info:
                        for k, v in info.items():
                            if isinstance(v, bytes):
                                try:
                                    v = v.decode('utf-8', errors='ignore')
                                except Exception:
                                    pass
                            metadata[k.lower()] = str(v)
                pages_count = sum(1 for _ in doc.get_pages())
        except Exception as e:
            logger.error(f"pdfminer metadata/pages extraction failed: {e}")

        return {
            "text": text or "",
            "pages": pages_count,
            "method": "direct",
            "metadata": metadata,
        }

    def _extract_ocr(self, pdf_path: Path) -> dict:
        """Extract text using OCR (for scanned PDFs)."""
        if not HAS_OCR:
            return {
                "text": "",
                "pages": 0,
                "method": "ocr",
                "error": "OCR dependencies not installed (pdf2image, pytesseract)",
                "metadata": {},
            }

        try:
            # Convert PDF to images
            images = convert_from_path(str(pdf_path))
            
            # OCR each page
            text_parts = []
            for img in images:
                text = pytesseract.image_to_string(img)
                text_parts.append(text)
            
            full_text = "\n\n".join(text_parts)
            
            return {
                "text": full_text,
                "pages": len(images),
                "method": "ocr",
                "metadata": {},
            }
        except Exception as e:
            return {
                "text": "",
                "pages": 0,
                "method": "ocr",
                "error": f"OCR extraction failed: {e}",
                "metadata": {},
            }

    def extract_from_bytes(self, pdf_bytes: bytes, use_ocr: bool = False) -> dict:
        """
        Extract text from PDF bytes.
        
        Args:
            pdf_bytes: PDF file content
            use_ocr: Enable OCR if no text found
            
        Returns:
            Extraction result dict
        """
        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)
        
        try:
            result = self.extract_text(tmp_path)
            return result
        finally:
            # Cleanup
            if tmp_path.exists():
                tmp_path.unlink()

