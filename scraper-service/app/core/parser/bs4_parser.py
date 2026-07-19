"""
BeautifulSoup4 parser implementation.
Returns a BeautifulSoup object — extractors operate on this.
"""

from __future__ import annotations
from bs4 import BeautifulSoup
from .base import BaseParser


class BS4Parser(BaseParser):
    """HTML parser using BeautifulSoup4 + lxml/html.parser backend."""

    def __init__(self, backend: str = "html.parser"):
        # "html.parser" = stdlib, "lxml" = faster (requires lxml installed)
        self._backend = backend

    def parse(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, self._backend)


# Default singleton — avoids re-creating parser on every call
default_parser = BS4Parser()
