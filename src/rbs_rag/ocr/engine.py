"""Main OCR Engine - High-level interface for OCR processing."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from rbs_rag.ocr.engines import create_orchestrator, OCROrchestrator
from rbs_rag.pdf.pipeline import PDFProcessor
from rbs_rag.preprocessing.preprocessor import ImagePreprocessor
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class OCRResult:
    """Result of OCR processing."""

    def __init__(
        self,
        filename: str,
        pages: list[dict[str, Any]],
        processing_time_ms: float,
        engine: str,
        error: Optional[str] = None,
    ):
        self.filename = filename
        self.pages = pages
        self.processing_time_ms = processing_time_ms
        self.engine = engine
        self.error = error

    @property
    def full_text(self) -> str:
        """Get full text from all pages."""
        return "\n\n".join(page.get("text", "") for page in self.pages)

    @property
    def total_words(self) -> int:
        """Get total word count."""
        return sum(page.get("word_count", 0) for page in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "pages": self.pages,
            "processing_time_ms": self.processing_time_ms,
            "engine": self.engine,
            "error": self.error,
            "full_text": self.full_text,
            "total_words": self.total_words,
        }


class OCREngine:
    """High-level OCR engine for processing images and PDFs."""

    def __init__(
        self,
        mistral_api_key: str = "",
        languages: list[str] = None,
        use_gpu: bool = False,
        primary_engine: str = "paddle",
        dpi: int = 150,
    ):
        self.mistral_api_key = mistral_api_key
        self.languages = languages or ["en"]
        self.use_gpu = use_gpu
        self.primary_engine = primary_engine
        self.dpi = dpi

        self.orchestrator = create_orchestrator(
            mistral_api_key=mistral_api_key,
            languages=self.languages,
            use_gpu=use_gpu,
            primary_engine=primary_engine,
        )
        self.pdf_processor = PDFProcessor(dpi=dpi)
        self.preprocessor = ImagePreprocessor()

    def process_image(self, image_path: Path) -> OCRResult:
        """Process a single image file."""
        t0 = time.time()
        
        try:
            # Preprocess image
            processed_path = self.preprocessor.preprocess(image_path)
            
            # Run OCR
            result = self.orchestrator.extract_text(processed_path)
            
            processing_time_ms = (time.time() - t0) * 1000
            
            page_data = {
                "page_number": 1,
                "text": result.get("text", ""),
                "regions": result.get("regions", []),
                "words": result.get("words", []),
                "word_count": len(result.get("words", [])),
                "confidence": self._avg_confidence(result.get("regions", [])),
            }
            
            return OCRResult(
                filename=image_path.name,
                pages=[page_data],
                processing_time_ms=processing_time_ms,
                engine=result.get("engine", "unknown"),
                error=result.get("error"),
            )
        except Exception as e:
            logger.error("Image OCR failed: %s", e)
            return OCRResult(
                filename=image_path.name,
                pages=[],
                processing_time_ms=(time.time() - t0) * 1000,
                engine="error",
                error=str(e),
            )

    def process_pdf(self, pdf_path: Path) -> OCRResult:
        """Process a PDF file - extracts text from digital PDFs or runs OCR on scanned pages."""
        t0 = time.time()
        
        try:
            # First, try to extract text directly from PDF
            pages_data = self.pdf_processor.extract_text(pdf_path)
            
            # Check if any page has substantial text (digital PDF)
            has_digital_text = any(
                len(page.get("text", "").strip()) > 50 for page in pages_data
            )
            
            if has_digital_text:
                # Digital PDF - use extracted text
                processing_time_ms = (time.time() - t0) * 1000
                return OCRResult(
                    filename=pdf_path.name,
                    pages=pages_data,
                    processing_time_ms=processing_time_ms,
                    engine="pymupdf",
                )
            
            # Scanned PDF - render pages and run OCR
            logger.info("PDF appears scanned, running OCR on rendered pages: %s", pdf_path.name)
            rendered_pages = self.pdf_processor.render_pages(pdf_path, dpi=self.dpi)
            
            all_pages = []
            for i, page_image in enumerate(rendered_pages):
                result = self.orchestrator.extract_text_from_bytes(page_image)
                
                page_data = {
                    "page_number": i + 1,
                    "text": result.get("text", ""),
                    "regions": result.get("regions", []),
                    "words": result.get("words", []),
                    "word_count": len(result.get("words", [])),
                    "confidence": self._avg_confidence(result.get("regions", [])),
                }
                all_pages.append(page_data)
            
            processing_time_ms = (time.time() - t0) * 1000
            
            return OCRResult(
                filename=pdf_path.name,
                pages=all_pages,
                processing_time_ms=processing_time_ms,
                engine=self.orchestrator.primary_engine.name if self.orchestrator.primary_engine else "unknown",
            )
        except Exception as e:
            logger.error("PDF OCR failed: %s", e)
            return OCRResult(
                filename=pdf_path.name,
                pages=[],
                processing_time_ms=(time.time() - t0) * 1000,
                engine="error",
                error=str(e),
            )

    def process(self, file_path: Path) -> OCRResult:
        """Process a file (image or PDF) automatically."""
        suffix = file_path.suffix.lower()
        
        if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
            return self.process_image(file_path)
        elif suffix == ".pdf":
            return self.process_pdf(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    def _avg_confidence(self, regions: list[dict]) -> float:
        """Calculate average confidence from regions."""
        if not regions:
            return 0.0
        confidences = [r.get("confidence", 0) for r in regions if r.get("confidence") is not None]
        return sum(confidences) / len(confidences) if confidences else 0.0