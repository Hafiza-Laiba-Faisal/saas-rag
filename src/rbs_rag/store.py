from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .models import Chunk, LoadedDocument

log = logging.getLogger(__name__)


class SQLiteRagStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    knowledge_base_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    ocr_applied INTEGER DEFAULT 0,
                    ocr_engine TEXT,
                    page_count INTEGER,
                    source TEXT DEFAULT 'upload',
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    knowledge_base_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                );
                CREATE TABLE IF NOT EXISTS session_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_memory (
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, user_id, key)
                );
                CREATE TABLE IF NOT EXISTS health (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._migrate_schema(connection)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        migrations = [
            "ALTER TABLE documents ADD COLUMN ocr_applied INTEGER DEFAULT 0",
            "ALTER TABLE documents ADD COLUMN ocr_engine TEXT",
            "ALTER TABLE documents ADD COLUMN page_count INTEGER",
            "ALTER TABLE documents ADD COLUMN source TEXT DEFAULT 'upload'",
            "ALTER TABLE documents ADD COLUMN source_url TEXT",
            "ALTER TABLE documents ADD COLUMN ingested_at TEXT DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE documents ADD COLUMN tenant_id TEXT",
            "ALTER TABLE documents ADD COLUMN knowledge_base_id TEXT",
        ]
        for stmt in migrations:
            try:
                connection.execute(stmt)
            except sqlite3.OperationalError:
                pass

    def upsert_document(self, document: LoadedDocument, tenant_id: str, knowledge_base_id: str, source: str = "upload", source_url: str | None = None) -> None:
        metadata = dict(document.metadata)
        metadata.update({"tenant_id": tenant_id, "knowledge_base_id": knowledge_base_id, "source": source})
        if source_url:
            metadata["source_url"] = source_url
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document.document_id,))
            connection.execute(
                """
                INSERT OR REPLACE INTO documents
                (document_id, tenant_id, knowledge_base_id, path, name, document_type, text, metadata_json, ocr_applied, ocr_engine, page_count, source, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    tenant_id,
                    knowledge_base_id,
                    document.path,
                    document.name,
                    document.document_type,
                    document.text,
                    json.dumps(metadata),
                    int(document.ocr_applied),
                    document.ocr_engine,
                    document.page_count,
                    source,
                    source_url,
                ),
            )

    def delete_document(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    def get_document(self, document_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row) | {"metadata": json.loads(row["metadata_json"])}

    def upsert_chunks(self, chunks: Iterable[Chunk]) -> None:
        rows = []
        for chunk in chunks:
            rows.append(
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.metadata["tenant_id"],
                    chunk.metadata["knowledge_base_id"],
                    chunk.ordinal,
                    chunk.text,
                    json.dumps(chunk.metadata),
                    json.dumps(chunk.embedding),
                )
            )
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO chunks
                (chunk_id, document_id, tenant_id, knowledge_base_id, ordinal, text, metadata_json, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            connection.execute(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", chunk_ids)

    def list_chunks(self, tenant_id: str, knowledge_base_id: str, filters: dict[str, str] | None = None) -> list[Chunk]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE tenant_id = ? AND knowledge_base_id = ? ORDER BY ordinal",
                (tenant_id, knowledge_base_id),
            ).fetchall()
        chunks = [self._row_to_chunk(row) for row in rows]
        if filters:
            chunks = [chunk for chunk in chunks if _metadata_matches(chunk.metadata, filters)]
        return chunks

    def list_documents(self, tenant_id: str, knowledge_base_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document_id, path, name, document_type, metadata_json, ocr_applied, ocr_engine, page_count, source, source_url, ingested_at
                FROM documents
                WHERE tenant_id = ? AND knowledge_base_id = ?
                ORDER BY name
                """,
                (tenant_id, knowledge_base_id),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(row["metadata_json"])
            d["ocr_applied"] = bool(row["ocr_applied"])
            result.append(d)
        return result

    def count_documents(self, tenant_id: str, knowledge_base_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM documents WHERE tenant_id = ? AND knowledge_base_id = ?",
                (tenant_id, knowledge_base_id),
            ).fetchone()
        return row["cnt"] if row else 0

    def count_chunks(self, tenant_id: str, knowledge_base_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM chunks WHERE tenant_id = ? AND knowledge_base_id = ?",
                (tenant_id, knowledge_base_id),
            ).fetchone()
        return row["cnt"] if row else 0

    def add_session_turn(self, tenant_id: str, session_id: str, user_id: str, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO session_turns (tenant_id, session_id, user_id, role, content) VALUES (?, ?, ?, ?, ?)",
                (tenant_id, session_id, user_id, role, content),
            )

    def get_session_memory(self, tenant_id: str, session_id: str, user_id: str, limit: int = 8) -> str:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM session_turns WHERE tenant_id = ? AND session_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
                (tenant_id, session_id, user_id, limit),
            ).fetchall()
        ordered = list(reversed(rows))
        return "\n".join(f"{row['role']}: {row['content']}" for row in ordered)

    def set_user_memory(self, tenant_id: str, user_id: str, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO user_memory (tenant_id, user_id, key, value) VALUES (?, ?, ?, ?)", (tenant_id, user_id, key, value))

    def get_user_memory(self, tenant_id: str, user_id: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM user_memory WHERE tenant_id = ? AND user_id = ? ORDER BY key", (tenant_id, user_id)).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def list_sessions(self, tenant_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id, user_id, COUNT(*) AS turns, MAX(created_at) AS last_turn_at FROM session_turns WHERE tenant_id = ? GROUP BY session_id, user_id ORDER BY last_turn_at DESC",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session_turns(self, tenant_id: str, session_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content, created_at FROM session_turns WHERE tenant_id = ? AND session_id = ? ORDER BY id ASC",
                (tenant_id, session_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, tenant_id: str, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM session_turns WHERE tenant_id = ? AND session_id = ?", (tenant_id, session_id))

    def purge_expired_sessions(self, tenant_id: str, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM session_turns WHERE tenant_id = ? AND created_at < datetime('now', '-' || ? || ' days')",
                (tenant_id, str(retention_days)),
            )
            return cursor.rowcount

    def set_health(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO health (key, value) VALUES (?, ?)", (key, value))

    def get_health(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM health WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            text=row["text"],
            metadata=json.loads(row["metadata_json"]),
            embedding=json.loads(row["embedding_json"]),
            ordinal=row["ordinal"],
        )


def _metadata_matches(metadata: dict, filters: dict[str, str]) -> bool:
    for key, expected in filters.items():
        actual = metadata.get(key)
        if isinstance(actual, list):
            if expected not in [str(item) for item in actual]:
                return False
        elif str(actual) != expected:
            return False
    return True
