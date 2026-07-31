import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from rbs_rag.security import decrypt_api_key, encrypt_api_key, hash_api_key, validate_api_key

_ADMIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id         TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    slug              TEXT NOT NULL,
    api_key           TEXT NOT NULL UNIQUE,
    api_key_hash      TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    subscription_tier TEXT NOT NULL DEFAULT 'basic',
    monthly_fee       REAL NOT NULL DEFAULT 299.0,
    llm_provider      TEXT NOT NULL DEFAULT 'gemini',
    llm_model         TEXT NOT NULL DEFAULT 'gemini-2.5-flash-lite',
    llm_api_key       TEXT NOT NULL,
    llm_base_url      TEXT,
    embedding_provider   TEXT NOT NULL DEFAULT 'hash',
    embedding_model      TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    embedding_dimensions INTEGER NOT NULL DEFAULT 384,
    embedding_base_url   TEXT,
    embedding_api_key    TEXT,
    retrieval_top_k          INTEGER NOT NULL DEFAULT 20,
    retrieval_rerank_top_k   INTEGER NOT NULL DEFAULT 8,
    retrieval_final_context_k INTEGER NOT NULL DEFAULT 5,
    retrieval_dense_weight   REAL NOT NULL DEFAULT 0.55,
    retrieval_sparse_weight  REAL NOT NULL DEFAULT 0.45,
    chunking_max_tokens        INTEGER NOT NULL DEFAULT 320,
    chunking_overlap_tokens    INTEGER NOT NULL DEFAULT 48,
    chunking_semantic          INTEGER NOT NULL DEFAULT 0,
    chunking_semantic_threshold REAL NOT NULL DEFAULT 0.75,
    reranker_type        TEXT NOT NULL DEFAULT 'local',
    session_memory_limit INTEGER NOT NULL DEFAULT 8,
    chat_retention_days  INTEGER NOT NULL DEFAULT 30,
    system_prompt        TEXT,
    db_path    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    TEXT,
    level        TEXT NOT NULL DEFAULT 'INFO',
    operation    TEXT NOT NULL,
    message      TEXT NOT NULL,
    latency_ms   REAL NOT NULL DEFAULT 0.0,
    details_json TEXT,
    traceback    TEXT,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS health (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(ddl)


class AdminStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.executescript(_ADMIN_SCHEMA)
            # Forward-compatible guards for pre-existing (old-schema) admin DBs.
            for col, ddl in [
                ("slug", "ALTER TABLE tenants ADD COLUMN slug TEXT"),
                ("db_path", "ALTER TABLE tenants ADD COLUMN db_path TEXT"),
                ("updated_at", "ALTER TABLE tenants ADD COLUMN updated_at TEXT"),
                ("chunking_semantic", "ALTER TABLE tenants ADD COLUMN chunking_semantic INTEGER DEFAULT 0"),
                ("chunking_semantic_threshold", "ALTER TABLE tenants ADD COLUMN chunking_semantic_threshold REAL DEFAULT 0.75"),
                ("reranker_type", "ALTER TABLE tenants ADD COLUMN reranker_type TEXT DEFAULT 'local'"),
                ("embedding_base_url", "ALTER TABLE tenants ADD COLUMN embedding_base_url TEXT"),
                ("embedding_api_key", "ALTER TABLE tenants ADD COLUMN embedding_api_key TEXT"),
                ("session_memory_limit", "ALTER TABLE tenants ADD COLUMN session_memory_limit INTEGER DEFAULT 8"),
                ("chat_retention_days", "ALTER TABLE tenants ADD COLUMN chat_retention_days INTEGER DEFAULT 30"),
                ("system_prompt", "ALTER TABLE tenants ADD COLUMN system_prompt TEXT"),
                ("api_key_hash", "ALTER TABLE tenants ADD COLUMN api_key_hash TEXT"),
            ]:
                _ensure_column(conn, "tenants", col, ddl)
            for col, ddl in [
                ("latency_ms", "ALTER TABLE activity_logs ADD COLUMN latency_ms REAL DEFAULT 0.0"),
                ("details_json", "ALTER TABLE activity_logs ADD COLUMN details_json TEXT"),
                ("traceback", "ALTER TABLE activity_logs ADD COLUMN traceback TEXT"),
            ]:
                _ensure_column(conn, "activity_logs", col, ddl)
            # One-time migration: old system_logs table -> activity_logs.
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "system_logs" in tables and "activity_logs" in tables:
                n = conn.execute(
                    """
                    INSERT OR IGNORE INTO activity_logs
                        (tenant_id, level, operation, message, traceback, details_json, created_at)
                    SELECT tenant_id, level, operation, message, traceback,
                           CASE WHEN details_json IS NOT NULL THEN details_json ELSE json_object('latency_ms', latency_ms) END,
                           created_at
                    FROM system_logs
                    WHERE tenant_id IS NOT NULL
                      AND tenant_id IN (SELECT tenant_id FROM tenants)
                    """
                ).rowcount
                if n:
                    conn.execute("DROP TABLE system_logs")
            conn.commit()

    # ── Activity logs ──────────────────────────────────────────────────────────

    def log_activity(
        self,
        tenant_id: str | None,
        level: str,
        operation: str,
        message: str,
        latency_ms: float = 0.0,
        traceback: str | None = None,
        details: dict | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_logs (tenant_id, level, operation, message, latency_ms, traceback, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    level.upper(),
                    operation,
                    message,
                    round(latency_ms, 2),
                    traceback or "",
                    json.dumps(details or {}),
                    _utcnow(),
                ),
            )
            conn.commit()

    def get_activity_logs(
        self, tenant_id: str | None = None, level: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = "SELECT * FROM activity_logs"
        params: list = []
        conditions = []
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if level:
            conditions.append("level = ?")
            params.append(level.upper())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    # ── Tenants ────────────────────────────────────────────────────────────────

    def _decrypt_tenant(self, row: dict) -> dict:
        d = dict(row)
        if d.get("llm_api_key"):
            d["llm_api_key"] = decrypt_api_key(d["llm_api_key"])
        if d.get("embedding_api_key"):
            d["embedding_api_key"] = decrypt_api_key(d["embedding_api_key"])
        return d

    def list_tenants(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tenants ORDER BY created_at DESC").fetchall()
            return [self._decrypt_tenant(dict(row)) for row in rows]

    def get_tenant(self, tenant_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
            return self._decrypt_tenant(dict(row)) if row else None

    def get_tenant_by_api_key(self, api_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tenants WHERE api_key = ?", (api_key,)).fetchone()
            if row is None:
                key_hash = hash_api_key(api_key)
                row = conn.execute("SELECT * FROM tenants WHERE api_key_hash = ?", (key_hash,)).fetchone()
            return self._decrypt_tenant(dict(row)) if row else None

    def upsert_tenant(self, data: dict) -> None:
        api_key_val = data.get("api_key", "")
        api_key_hash = hash_api_key(api_key_val) if api_key_val else None
        llm_api_key_enc = encrypt_api_key(data["llm_api_key"])
        embedding_api_key_enc = encrypt_api_key(data.get("embedding_api_key", ""))
        now = _utcnow()

        columns = [
            "tenant_id", "name", "slug", "status", "subscription_tier", "monthly_fee",
            "api_key", "api_key_hash", "llm_provider", "llm_model", "llm_api_key", "llm_base_url",
            "embedding_provider", "embedding_model", "embedding_dimensions", "embedding_base_url", "embedding_api_key",
            "retrieval_top_k", "retrieval_rerank_top_k", "retrieval_final_context_k",
            "retrieval_dense_weight", "retrieval_sparse_weight",
            "chunking_max_tokens", "chunking_overlap_tokens", "chunking_semantic", "chunking_semantic_threshold",
            "reranker_type", "session_memory_limit", "chat_retention_days", "system_prompt",
            "db_path", "created_at", "updated_at",
        ]
        values = [
            data["tenant_id"], data["name"], data.get("slug", data["tenant_id"]), data["status"], data["subscription_tier"], data["monthly_fee"],
            api_key_val or None, api_key_hash, data["llm_provider"], data["llm_model"], llm_api_key_enc, data.get("llm_base_url"),
            data["embedding_provider"], data["embedding_model"], data["embedding_dimensions"], data.get("embedding_base_url"), embedding_api_key_enc,
            data["retrieval_top_k"], data["retrieval_rerank_top_k"], data["retrieval_final_context_k"],
            data["retrieval_dense_weight"], data["retrieval_sparse_weight"],
            data["chunking_max_tokens"], data["chunking_overlap_tokens"], int(data.get("chunking_semantic", 0)), data.get("chunking_semantic_threshold", 0.75),
            data.get("reranker_type", "local"), data.get("session_memory_limit", 8), data.get("chat_retention_days", 30), data.get("system_prompt"),
            data["db_path"], data.get("created_at", now), now,
        ]

        update_cols = [c for c in columns if c not in ("tenant_id", "created_at")]
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO tenants ({', '.join(columns)})
                VALUES ({', '.join('?' for _ in columns)})
                ON CONFLICT(tenant_id) DO UPDATE SET {set_clause}
                """,
                values,
            )
            conn.commit()

    def delete_tenant(self, tenant_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
