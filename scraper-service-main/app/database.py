"""
SQLite database layer for storing scraped Facebook posts.
Uses Python's built-in sqlite3 — no extra dependencies needed.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "scraper.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # dict-like rows
    conn.execute("PRAGMA journal_mode=WAL") # better concurrency
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist, and run migrations for existing DBs."""
    with get_conn() as conn:
        # Step 1: Create tables (without indexes that depend on new columns)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scrape_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                page_url    TEXT    NOT NULL,
                page_title  TEXT,
                page_image  TEXT,
                page_desc   TEXT,
                page_meta   TEXT,
                scraped_at  TEXT    NOT NULL,
                posts_count INTEGER DEFAULT 0,
                reels_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS posts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES scrape_sessions(id) ON DELETE CASCADE,
                post_id     TEXT    NOT NULL,
                caption     TEXT,
                media       TEXT,
                likes       INTEGER DEFAULT 0,
                comments    INTEGER DEFAULT 0,
                shares      INTEGER DEFAULT 0,
                posted_at   TEXT,
                post_url    TEXT,
                saved_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Step 2: Migrations — add columns that may not exist in older DBs
        migrations = [
            ("scrape_sessions", "page_meta",    "TEXT"),
            ("scrape_sessions", "reels_count",  "INTEGER DEFAULT 0"),
            ("posts",           "content_type", "TEXT NOT NULL DEFAULT 'post'"),
        ]
        for table, col, definition in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                conn.commit()
            except Exception:
                pass  # column already exists

        # Step 3: Create indexes (now safe — all columns exist)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_posts_session  ON posts(session_id);
            CREATE INDEX IF NOT EXISTS idx_posts_post_id  ON posts(post_id);
            CREATE INDEX IF NOT EXISTS idx_posts_type     ON posts(content_type);
            CREATE INDEX IF NOT EXISTS idx_sessions_url   ON scrape_sessions(page_url);
        """)

# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(page_url: str, page_meta: dict, posts: list, reels: list = None) -> int:
    """Save a full scrape result (posts + reels separately). Returns session_id."""
    now = datetime.now().isoformat(timespec="seconds")
    reels = reels or []

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO scrape_sessions
               (page_url, page_title, page_image, page_desc, page_meta, scraped_at, posts_count, reels_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                page_url,
                page_meta.get("title", ""),
                page_meta.get("cover_image", ""),
                page_meta.get("description", ""),
                json.dumps(page_meta, ensure_ascii=False),
                now,
                len(posts),
                len(reels),
            ),
        )
        session_id = cur.lastrowid

        def _insert_items(items, content_type):
            for p in items:
                conn.execute(
                    """INSERT INTO posts
                       (session_id, post_id, content_type, caption, media, likes, comments, shares, posted_at, post_url, saved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        p.get("id", ""),
                        content_type,
                        p.get("caption", ""),
                        json.dumps(p.get("media", []), ensure_ascii=False),
                        int(p.get("likes", 0) or 0),
                        int(p.get("comments", 0) or 0),
                        int(p.get("shares", 0) or 0),
                        p.get("postedAt", ""),
                        p.get("postUrl", ""),
                        now,
                    ),
                )

        _insert_items(posts, "post")
        _insert_items(reels, "reel")

    return session_id


def list_sessions() -> list[dict]:
    """Return all sessions, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scrape_sessions ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: int) -> Optional[dict]:
    """Return one session + its posts."""
    with get_conn() as conn:
        session_row = conn.execute(
            "SELECT * FROM scrape_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not session_row:
            return None
        session = dict(session_row)
    # Parse full page_meta JSON if available
    if session.get("page_meta"):
        try:
            session["page_meta"] = json.loads(session["page_meta"])
        except Exception:
            pass

        post_rows = conn.execute(
            "SELECT * FROM posts WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()

    posts = []
    for r in post_rows:
        p = dict(r)
        p["media"] = json.loads(p["media"] or "[]")
        posts.append(p)

    session["posts"] = posts
    return session


def delete_session(session_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM scrape_sessions WHERE id = ?", (session_id,)
        )
    return cur.rowcount > 0


def get_all_posts(
    search: str = "",
    page_url_filter: str = "",
    content_type: str = "",
    date_from: str = "",   # YYYY-MM-DD
    date_to: str = "",     # YYYY-MM-DD
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Return paginated posts/reels across all sessions with optional search + date range."""
    where_clauses = []
    params: list = []

    if search.strip():
        where_clauses.append("p.caption LIKE ?")
        params.append(f"%{search.strip()}%")

    if page_url_filter.strip():
        where_clauses.append("s.page_url LIKE ?")
        params.append(f"%{page_url_filter.strip()}%")

    if content_type.strip():
        where_clauses.append("p.content_type = ?")
        params.append(content_type.strip())

    if date_from.strip():
        where_clauses.append("p.posted_at >= ?")
        params.append(date_from.strip()[:10])

    if date_to.strip():
        where_clauses.append("p.posted_at <= ?")
        params.append(date_to.strip()[:10] + " 23:59:59")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT p.*, s.page_url, s.page_title, s.scraped_at as session_scraped_at
        FROM posts p
        JOIN scrape_sessions s ON p.session_id = s.id
        {where_sql}
        ORDER BY p.posted_at DESC, p.id DESC
        LIMIT ? OFFSET ?
    """
    count_query = f"""
        SELECT COUNT(*) FROM posts p
        JOIN scrape_sessions s ON p.session_id = s.id
        {where_sql}
    """

    with get_conn() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        rows  = conn.execute(query, params + [limit, offset]).fetchall()

    posts = []
    for r in rows:
        p = dict(r)
        p["media"] = json.loads(p["media"] or "[]")
        posts.append(p)

    return {"total": total, "posts": posts}


def delete_post(post_db_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM posts WHERE id = ?", (post_db_id,))
    return cur.rowcount > 0


def get_stats() -> dict:
    with get_conn() as conn:
        total_sessions   = conn.execute("SELECT COUNT(*) FROM scrape_sessions").fetchone()[0]
        total_posts      = conn.execute("SELECT COUNT(*) FROM posts WHERE content_type='post'").fetchone()[0]
        total_reels      = conn.execute("SELECT COUNT(*) FROM posts WHERE content_type='reel'").fetchone()[0]
        total_with_media = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE media != '[]' AND media IS NOT NULL"
        ).fetchone()[0]
        pages = conn.execute(
            "SELECT DISTINCT page_url, page_title FROM scrape_sessions ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return {
        "total_sessions":   total_sessions,
        "total_posts":      total_posts,
        "total_reels":      total_reels,
        "total_with_media": total_with_media,
        "pages": [dict(p) for p in pages],
    }


def save_fb_cookies(cookies: dict) -> None:
    """Persist Facebook session cookies to DB so they survive server restarts."""
    with get_conn() as conn:
        import json as _json
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("fb_cookies", _json.dumps(cookies), datetime.now().isoformat()),
        )


def load_fb_cookies() -> dict:
    """Load persisted Facebook cookies from DB. Returns {} if none saved."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'fb_cookies'"
            ).fetchone()
        if row:
            import json as _json
            return _json.loads(row[0])
    except Exception:
        pass
    return {}


def clear_fb_cookies() -> None:
    """Remove saved Facebook cookies."""
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = 'fb_cookies'")
    except Exception:
        pass


# Auto-init on import
init_db()
