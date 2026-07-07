"""Mistral OCR engine implementation (cloud/primary)."""
from __future__ import annotations

import base64
import logging
import re
from typing import List

from ocr.engines.base import BaseOCREngine
from schemas.ocr import PageResult, ExtractedEntities

logger = logging.getLogger(__name__)


class MistralOCREngine(BaseOCREngine):
    """Uses Mistral Document AI OCR API for high-quality text and table extraction."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = None
        if api_key:
            try:
                try:
                    from mistralai import Mistral
                except ImportError:
                    from mistralai.client import Mistral
                self._client = Mistral(api_key=api_key)
                logger.info("MistralOCREngine initialized successfully")
            except Exception as e:
                logger.warning("MistralOCREngine could not initialize: %s", e)

    def is_available(self) -> bool:
        return self._client is not None and bool(self._api_key)

    def process_image(self, image_data: bytes, filename: str) -> PageResult:
        """Process image bytes through Mistral OCR API."""
        b64 = base64.b64encode(image_data).decode("utf-8")

        # Detect MIME type from filename
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp", "avif": "image/avif"}
        mime = mime_map.get(ext, "image/png")

        data_url = f"data:{mime};base64,{b64}"

        ocr_response = self._client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "image_url", "image_url": data_url},
            table_format="html",
            include_image_base64=False,
        )

        return self._parse_response(ocr_response, page_offset=0)[0]

    def process_pdf(self, pdf_bytes: bytes, filename: str) -> List[PageResult]:
        """Process full PDF through Mistral OCR API (base64 encoded)."""
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        data_url = f"data:application/pdf;base64,{b64}"

        ocr_response = self._client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "document_url", "document_url": data_url},
            table_format="html",
            include_image_base64=False,
        )

        return self._parse_response(ocr_response, page_offset=0)

    @staticmethod
    def _parse_response(ocr_response, page_offset: int = 0) -> List[PageResult]:
        """Convert Mistral OCR response to our standard PageResult list."""
        pages: List[PageResult] = []

        for page_data in ocr_response.pages:
            page_idx = getattr(page_data, "index", page_offset + len(pages))
            markdown_text = getattr(page_data, "markdown", "") or ""

            # Extract plain text from markdown (strip markdown syntax for full_text)
            plain_text = _markdown_to_plain(markdown_text)

            # Extract tables
            raw_tables = getattr(page_data, "tables", []) or []
            table_htmls = []
            for tbl in raw_tables:
                content = getattr(tbl, "content", None) or (tbl if isinstance(tbl, str) else "")
                if content:
                    table_htmls.append(content)

            # Extract hyperlinks
            raw_links = getattr(page_data, "hyperlinks", []) or []
            hyperlinks = []
            for link in raw_links:
                if isinstance(link, str):
                    hyperlinks.append(link)
                else:
                    hyperlinks.append(str(link))

            # Build paragraphs, lines, words from plain text
            paragraphs = [p.strip() for p in plain_text.split("\n\n") if p.strip()]
            lines = [l.strip() for l in plain_text.splitlines() if l.strip()]
            words = plain_text.split()

            pages.append(PageResult(
                page_number=page_idx + 1,  # 1-indexed
                full_text=plain_text,
                markdown=markdown_text,
                tables=table_htmls,
                hyperlinks=hyperlinks,
                paragraphs=paragraphs,
                lines=lines,
                words=words,
                regions=[],
                entities=ExtractedEntities(),
            ))

        if not pages:
            pages.append(PageResult(
                page_number=1,
                full_text="",
                paragraphs=[],
                lines=[],
                words=[],
                regions=[],
                entities=ExtractedEntities(),
            ))

        return pages


def _markdown_to_plain(md: str) -> str:
    """Strip basic markdown formatting to produce plain text."""
    text = md
    # Remove image refs
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove headers markers
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
    # Clean up extra whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
