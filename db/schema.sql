-- TenBit RAG Platform — admin.db schema (shared, single file)
-- Applies idempotently; safe to re-run any number of times.
-- Per-tenant data lives in tenants/<slug>/rag.db (see tenant_schema.sql).

PRAGMA foreign_keys = ON;

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

-- NOTE: billing_events is intentionally DEFERRED (future invoicing feature).
-- Do not create the table now; add it via the migration runner when the
-- billing module is built. See provisioning.run_tenant_migrations().
