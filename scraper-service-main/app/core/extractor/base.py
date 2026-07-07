"""
Extractor interfaces — convert a parse tree into structured data.
Separate extractors for content, metadata, links, and assets.
Only one implementation should be active per extractor type at runtime.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseExtractor(ABC):
    """Base interface. All extractors accept a parse tree and return structured data."""

    @abstractmethod
    def extract(self, tree: Any, url: str = "") -> dict:
        ...


class ContentExtractor(BaseExtractor):
    """Extracts main text content from a parse tree."""
    ...


class MetadataExtractor(BaseExtractor):
    """Extracts page metadata: title, description, og tags, canonical URL."""
    ...


class LinksExtractor(BaseExtractor):
    """Extracts all links from a parse tree."""
    ...


class AssetsExtractor(BaseExtractor):
    """Extracts media assets: images, videos, audio."""
    ...
