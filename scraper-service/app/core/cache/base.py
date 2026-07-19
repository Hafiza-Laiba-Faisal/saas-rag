"""
Cache interface — abstract persistence.
Initial: in-memory. Future: Redis, disk.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseCache(ABC):

    @abstractmethod
    def get(self, key: str) -> Any | None:
        ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...
