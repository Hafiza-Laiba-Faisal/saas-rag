"""
Image metadata and OCR text extraction.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


class ImageExtractor:
    """
    Extract metadata and text from images.
    
    Features:
    - Image dimensions
    - File size
    - Format
    - EXIF data (optional)
    - OCR text extraction (optional)
    """

    def __init__(self, extract_text: bool = False):
        """
        Initialize image extractor.
        
        Args:
            extract_text: Enable OCR text extraction (requires pytesseract)
        """
        self.extract_text = extract_text and HAS_OCR

        if not HAS_PIL:
            raise ImportError("Pillow not installed. Run: pip install Pillow")

    def extract(self, image_path: str | Path, include_exif: bool = False) -> dict:
        """
        Extract metadata from image.
        
        Args:
            image_path: Path to image file
            include_exif: Extract EXIF metadata
            
        Returns:
            {
                "width": int,
                "height": int,
                "format": str,
                "mode": str,
                "size_bytes": int,
                "exif": dict (optional),
                "text": str (optional, if OCR enabled)
            }
        """
        image_path = Path(image_path)
        
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        with Image.open(image_path) as img:
            result = {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": image_path.stat().st_size,
            }

            # EXIF data
            if include_exif:
                exif_data = img.getexif()
                if exif_data:
                    result["exif"] = {
                        str(k): str(v) for k, v in exif_data.items()
                    }

            # OCR text extraction
            if self.extract_text and HAS_OCR:
                try:
                    text = pytesseract.image_to_string(img)
                    result["text"] = text.strip()
                except Exception as e:
                    result["text_error"] = str(e)

        return result

    def extract_from_bytes(self, image_bytes: bytes) -> dict:
        """Extract metadata from image bytes."""
        import io
        
        img = Image.open(io.BytesIO(image_bytes))
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "size_bytes": len(image_bytes),
        }
