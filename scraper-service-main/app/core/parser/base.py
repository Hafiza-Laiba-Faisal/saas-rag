"""
Parser interface — converts raw HTML into a parse tree.
Parser NEVER extracts business data. That is the extractor's job.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """Returns a parse tree object. Callers pass the tree to extractors."""

    @abstractmethod
    def parse(self, html: str) -> Any:
        """Parse HTML string and return a parse tree (BeautifulSoup, lxml root, etc.)."""
        ...
