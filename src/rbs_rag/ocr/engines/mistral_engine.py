from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from .base import BaseOCREngine


class MistralOCREngine(BaseOCREngine):
    """Mistral OCR API engine."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")
        self.base_url = "https://api.mistral.ai/v1/ocr"
        self._available = bool(self.api_key)

    @property
    def name(self) -> str:
        return "Mistral OCR"

    def is_available(self) -> bool:
        return self._available

    def extract_text(self, image_path: Path) -> dict[str, Any]:
        with image_path.open("rb") as f:
            image_bytes = f.read()
        return self.extract_text_from_bytes(image_bytes)

    def extract_text_from_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        if not self.is_available():
            return {"text": "", "regions": [], "words": [], "error": "No API key configured"}

        try:
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "model": "mistral-ocr-latest",
                "document": {
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{b64_image}"
                },
                "include_image_base64": False,
            }

            with httpx.Client(timeout=60.0) as client:
                response = client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return self._parse_mistral_result(result)
        except Exception as e:
            return {"text": "", "regions": [], "words": [], "error": str(e)}

    def _parse_mistral_result(self, result: dict) -> dict[str, Any]:
        """Parse Mistral OCR API response."""
        pages = result.get("pages", [])
        regions = []
        words = []
        full_text_parts = []

        for page in pages:
            page_text = page.get("markdown", "")
            full_text_parts.append(page_text)
            
            # Parse words from markdown
            page_words = page_text.split()
            words.extend(page_words)
            
            # Create regions from markdown blocks (simplified)
            if page_text.strip():
                regions.append({
                    "text": page_text,
                    "confidence": 0.95,  # Mistral doesn't provide per-region confidence
                    "bounding_box": [0, 0, 1000, 1000],  # Placeholder
                })

        return {
            "text": "\n\n".join(full_text_parts),
            "regions": regions,
            "words": words,
        }