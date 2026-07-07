"""
Cookie persistence layer — import/export, parse raw strings, storage bridge.
Decoupled from fb_auth so other platforms can use it too.
"""

from __future__ import annotations
from typing import Optional


class CookieStore:
    """
    Manages named cookie sets.
    Each 'key' is a scope (e.g. 'facebook', 'instagram').
    Loaded from storage on startup, persisted on write.
    """

    def __init__(self, storage=None):
        # Accept storage via DI; lazy-import default if not provided
        self._storage = storage
        self._cache: dict[str, dict] = {}

    def _get_storage(self):
        if self._storage is None:
            from storage.sqlite_storage import default_storage
            self._storage = default_storage
        return self._storage

    def load(self, key: str) -> dict:
        """Load cookies from persistent storage into memory cache."""
        if key not in self._cache:
            cookies = self._get_storage().load_cookies(key)
            if cookies:
                self._cache[key] = cookies
        return self._cache.get(key, {})

    def save(self, key: str, cookies: dict) -> None:
        """Persist cookies and update memory cache."""
        self._cache[key]  = cookies
        self._get_storage().save_cookies(key, cookies)

    def clear(self, key: str) -> None:
        self._cache.pop(key, None)
        self._get_storage().clear_cookies(key)

    def get(self, key: str) -> dict:
        return self._cache.get(key) or self.load(key)

    def has(self, key: str) -> bool:
        c = self.get(key)
        return bool(c)

    @staticmethod
    def parse_cookie_string(raw: str) -> dict:
        """
        Parse a raw document.cookie string like:
          "c_user=123; xs=abc; datr=xyz"
        Returns a flat dict.
        """
        result = {}
        for part in raw.split(";"):
            if "=" in part:
                k, _, v = part.strip().partition("=")
                result[k.strip()] = v.strip()
        return result

    @staticmethod
    def export_cookie_string(cookies: dict) -> str:
        """Convert a dict back to a cookie header string."""
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


# Module-level default instance
default_cookie_store = CookieStore()
