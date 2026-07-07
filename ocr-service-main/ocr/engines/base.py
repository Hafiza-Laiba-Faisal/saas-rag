"""Abstract base class for OCR engines."""
from abc import ABC, abstractmethod
import numpy as np
from typing import List, Tuple, Dict, Any, Union

from schemas.ocr import PageResult

class BaseOCREngine(ABC):
    """Abstract interface for all OCR engines.
    
    This ensures that regardless of the backend (PaddleOCR, Mistral, Google Vision),
    the services can interact with a unified interface.
    """
    
    @abstractmethod
    def process_image(self, image_data: bytes, filename: str) -> PageResult:
        """Process a single image and return a PageResult.
        
        Args:
            image_data: Raw image bytes
            filename: Original filename for reference
            
        Returns:
            PageResult containing extracted text, regions, and optional markdown/tables.
        """
        pass
        
    @abstractmethod
    def process_pdf(self, pdf_bytes: bytes, filename: str) -> List[PageResult]:
        """Process a PDF and return a list of PageResults (one per page).
        
        Args:
            pdf_bytes: Raw PDF bytes
            filename: Original filename
            
        Returns:
            List of PageResult objects.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is properly configured and available.
        
        Returns:
            True if ready to use, False otherwise.
        """
        pass
