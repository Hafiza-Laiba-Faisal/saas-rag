"""
Formatter interface — converts extracted data into output formats.
Supported: JSON, Markdown, HTML. Future: XML, CSV.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Literal

OutputFormat = Literal["json", "markdown", "html"]


class BaseFormatter(ABC):
    format: OutputFormat

    @abstractmethod
    def format_post(self, post: dict) -> str:
        ...

    @abstractmethod
    def format_page(self, page_meta: dict, posts: list[dict]) -> str:
        ...
