"""
SQLite storage implementation — wraps existing database.py functions.
Drop-in replacement for direct database.py imports.
Future: replace with PostgresStorage without touching any other module.
"""

from __future__ import annotations
from typing import Optional
from .base import BaseStorage


class SQLiteStorage(BaseStorage):
    """Thin adapter over the existing database.py module."""

    # ── Sessions ──────────────────────────────────────────────────────────────

    def save_session(self, page_url: str, page_meta: dict,
                     posts: list, reels: list) -> int:
        from database import save_session
        return save_session(page_url=page_url, page_meta=page_meta,
                            posts=posts, reels=reels)

    def list_sessions(self) -> list[dict]:
        from database import list_sessions
        return list_sessions()

    def get_session(self, session_id: int) -> Optional[dict]:
        from database import get_session
        return get_session(session_id)

    def delete_session(self, session_id: int) -> bool:
        from database import delete_session
        return delete_session(session_id)

    # ── Posts ─────────────────────────────────────────────────────────────────

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
        from database import get_all_posts
        return get_all_posts(
            search=search,
            page_url_filter=page_url_filter,
            content_type=content_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    def delete_post(self, post_db_id: int) -> bool:
        from database import delete_post
        return delete_post(post_db_id)

    def get_stats(self) -> dict:
        from database import get_stats
        return get_stats()

    # ── Cookies ───────────────────────────────────────────────────────────────

    def save_cookies(self, key: str, cookies: dict) -> None:
        from database import save_fb_cookies
        save_fb_cookies(cookies)

    def load_cookies(self, key: str) -> dict:
        from database import load_fb_cookies
        return load_fb_cookies()

    def clear_cookies(self, key: str) -> None:
        from database import clear_fb_cookies
        clear_fb_cookies()


# Module-level default instance — import this everywhere
default_storage = SQLiteStorage()
