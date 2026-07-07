"""OCR Service for integrating with RAG pipeline"""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any, Optional

from rbs_rag.ocr.engine import OCREngine, OCRResult
from rbs_rag.utils.logger import get_logger

logger = get_logger(__name__)


class OCRService:
    """Service for OCR processing in the RAG pipeline."""

    def __init__(
        self,
        mistral_api_key: str = "",
        languages: list[str] = None,
        use_gpu: bool = False,
        primary_engine: str = "paddle",
        dpi: int = 150,
    ):
        self.engine = OCREngine(
            mistral_api_key=mistral_api_key,
            languages=languages,
            use_gpu=use_gpu,
            primary_engine=primary_engine,
            dpi=dpi,
        )
        self._cache = {}

    def _get_cache_key(self, file_path: Path) -> str:
        """Generate cache key from file path and modification time."""
        stat = file_path.stat()
        return hashlib.md5(f"{file_path}:{stat.st_mtime}:{stat.st_size}".encode()).hexdigest()

    def process(self, file_path: Path, use_cache: bool = True) -> OCRResult:
        """Process a file through OCR."""
        cache_key = self._get_cache_key(file_path)
        
        if use_cache and cache_key in self._cache:
            logger.info("OCR cache hit for %s", file_path.name)
            return self._cache[cache_key]

        logger.info("Processing %s with OCR...", file_path.name)
        result = self.engine.process(file_path)
        
        if use_cache and not result.error:
            self._cache[cache_key] = result
        
        return result

    async def process_async(self, file_path: Path, use_cache: bool = True) -> OCRResult:
        """Process a file through OCR asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.process, file_path, use_cache)

    def clear_cache(self):
        """Clear OCR result cache."""
        self._cache.clear()

    def get_available_engines(self) -> list[str]:
        """Get list of available OCR engines."""
        return self.engine.orchestrator.get_available_engines()