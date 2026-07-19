"""
In-memory cache with TTL expiration.
Thread-safe. Future: replace with Redis without changing callers.
"""

from __future__ import annotations
import time
import threading
from typing import Any
from .base import BaseCache


class MemoryCache(BaseCache):

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}   # key → (value, expires_at)
        self._lock  = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_seconds)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# Module-level default instance
default_cache = MemoryCache()

# Cloudflare clearance cookie cache (per-domain, short TTL)
# Separate from default_cache so it can be independently monitored/flushed.
cf_cache = MemoryCache()
