"""
Fetcher interface — responsible ONLY for HTTP requests.
No parsing, no extraction, no business logic.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FetchResult:
    url:          str
    status_code:  int
    content:      bytes
    headers:      dict
    elapsed_ms:   float = 0.0
    final_url:    str   = ""
    cookies:      dict  = field(default_factory=dict)
    error:        Optional[str] = None

    @property
    def text(self) -> str:
        encoding = self._detect_encoding()
        return self.content.decode(encoding, errors="replace")

    def _detect_encoding(self) -> str:
        ct = self.headers.get("content-type", "")
        if "charset=" in ct:
            return ct.split("charset=")[-1].split(";")[0].strip()
        return "utf-8"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class BaseFetcher(ABC):
    """Interface for all HTTP fetchers. Swap implementations without changing callers."""

    @abstractmethod
    def fetch(
        self,
        url:     str,
        method:  str = "GET",
        headers: dict | None = None,
        timeout: int = 30,
        **kwargs,
    ) -> FetchResult:
        ...

    def get(self, url: str, headers: dict | None = None, timeout: int = 30) -> FetchResult:
        return self.fetch(url, "GET", headers=headers, timeout=timeout)
