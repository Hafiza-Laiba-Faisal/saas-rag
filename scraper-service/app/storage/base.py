"""
Storage interface — abstract persistence layer.
Initial: SQLite. Future: PostgreSQL, S3, MinIO — swap without changing callers.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional


class BaseStorage(ABC):

    # ── Sessions ──────────────────────────────────────────────────────────────

    @abstractmethod
    def save_session(self, page_url: str, page_meta: dict,
                     posts: list, reels: list) -> int:
        ...

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        ...

    @abstractmethod
    def get_session(self, session_id: int) -> Optional[dict]:
        ...

    @abstractmethod
    def delete_session(self, session_id: int) -> bool:
        ...

    # ── Posts ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_all_posts(
        self,
        search:          str = "",
        page_url_filter: str = "",
        content_type:    str = "",
        date_from:       str = "",
        date_to:         str = "",
        limit:           int = 100,
        offset:          int = 0,
    ) -> dict:
        ...

    @abstractmethod
    def delete_post(self, post_db_id: int) -> bool:
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        ...

    # ── Cookies ───────────────────────────────────────────────────────────────

    @abstractmethod
    def save_cookies(self, key: str, cookies: dict) -> None:
        ...

    @abstractmethod
    def load_cookies(self, key: str) -> dict:
        ...

    @abstractmethod
    def clear_cookies(self, key: str) -> None:
        ...
