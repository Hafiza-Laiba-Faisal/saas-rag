"""
Renderer interface — responsible ONLY for JavaScript rendering.
Returns rendered HTML. Never parses or extracts.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RenderResult:
    url:         str
    html:        str
    status_code: int   = 200
    final_url:   str   = ""
    elapsed_ms:  float = 0.0


class BaseRenderer(ABC):
    """Interface for all JS renderers. Playwright, Selenium, etc."""

    @abstractmethod
    def render(
        self,
        url:         str,
        wait_ms:     int  = 3000,
        cookies:     dict | None = None,
        user_agent:  str  = "",
        **kwargs,
    ) -> RenderResult:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
