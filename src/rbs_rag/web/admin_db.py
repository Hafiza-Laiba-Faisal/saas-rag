import json
import sqlite3
from pathlib import Path

from rbs_rag.security import decrypt_api_key, encrypt_api_key, hash_api_key, validate_api_key


class AdminStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL, -- 'active', 'suspended'
                    subscription_tier TEXT NOT NULL, -- 'basic', 'premium', 'enterprise'
                    monthly_fee REAL NOT NULL,
                    api_key TEXT,
                    api_key_hash TEXT,
                    llm_provider TEXT NOT NULL,
                    llm_model TEXT NOT NULL,
                    llm_api_key TEXT NOT NULL,
                    llm_base_url TEXT,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    embedding_base_url TEXT,
                    embedding_api_key TEXT,
                    retrieval_top_k INTEGER NOT NULL,
                    retrieval_rerank_top_k INTEGER NOT NULL,
                    retrieval_final_context_k INTEGER NOT NULL,
                    retrieval_dense_weight REAL NOT NULL,
                    retrieval_sparse_weight REAL NOT NULL,
                    chunking_max_tokens INTEGER NOT NULL,
                    chunking_overlap_tokens INTEGER NOT NULL,
                    session_memory_limit INTEGER DEFAULT 8,
                    chat_retention_days INTEGER DEFAULT 30,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Safe schema migrations for existing databases
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN embedding_base_url TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN embedding_api_key TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN session_memory_limit INTEGER DEFAULT 8")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN chat_retention_days INTEGER DEFAULT 30")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN api_key_hash TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN system_prompt TEXT")
            except sqlite3.OperationalError:
                pass

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT,
                    level TEXT NOT NULL, -- 'INFO', 'WARNING', 'ERROR'
                    operation TEXT NOT NULL,
                    message TEXT NOT NULL,
                    latency_ms REAL DEFAULT 0.0,
                    traceback TEXT,
                    details_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

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
                INSERT INTO system_logs (tenant_id, level, operation, message, latency_ms, traceback, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    level.upper(),
                    operation,
                    message,
                    round(latency_ms, 2),
                    traceback or "",
                    json.dumps(details or {}),
                ),
            )
            conn.commit()

    def get_activity_logs(
        self, tenant_id: str | None = None, level: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = "SELECT * FROM system_logs"
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
            conn.commit()

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
        key_hash = hash_api_key(api_key)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tenants WHERE api_key_hash = ?", (key_hash,)).fetchone()
            return self._decrypt_tenant(dict(row)) if row else None

    def upsert_tenant(self, data: dict) -> None:
        api_key_val = data.get("api_key", "")
        api_key_hash = hash_api_key(api_key_val) if api_key_val else None
        llm_api_key_enc = encrypt_api_key(data["llm_api_key"])
        embedding_api_key_enc = encrypt_api_key(data.get("embedding_api_key", ""))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tenants (
                    tenant_id, name, status, subscription_tier, monthly_fee, api_key, api_key_hash,
                    llm_provider, llm_model, llm_api_key, llm_base_url,
                    embedding_provider, embedding_model, embedding_dimensions,
                    embedding_base_url, embedding_api_key,
                    retrieval_top_k, retrieval_rerank_top_k, retrieval_final_context_k,
                    retrieval_dense_weight, retrieval_sparse_weight,
                    chunking_max_tokens, chunking_overlap_tokens,
                    session_memory_limit, chat_retention_days, system_prompt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["tenant_id"],
                    data["name"],
                    data["status"],
                    data["subscription_tier"],
                    data["monthly_fee"],
                    api_key_val or None,
                    api_key_hash,
                    data["llm_provider"],
                    data["llm_model"],
                    llm_api_key_enc,
                    data.get("llm_base_url"),
                    data["embedding_provider"],
                    data["embedding_model"],
                    data["embedding_dimensions"],
                    data.get("embedding_base_url"),
                    embedding_api_key_enc,
                    data["retrieval_top_k"],
                    data["retrieval_rerank_top_k"],
                    data["retrieval_final_context_k"],
                    data["retrieval_dense_weight"],
                    data["retrieval_sparse_weight"],
                    data["chunking_max_tokens"],
                    data["chunking_overlap_tokens"],
                    data.get("session_memory_limit", 8),
                    data.get("chat_retention_days", 30),
                    data.get("system_prompt"),
                ),
            )
            conn.commit()

    def delete_tenant(self, tenant_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
