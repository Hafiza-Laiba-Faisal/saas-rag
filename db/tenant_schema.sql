-- TenBit RAG Platform — per-tenant rag.db schema (isolated, one file per tenant)
-- Applies idempotently; safe to re-run any number of times.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS documents (
    document_id       TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL DEFAULT 'default',
    path              TEXT NOT NULL,
    name              TEXT NOT NULL,
    document_type     TEXT NOT NULL,
    text              TEXT NOT NULL,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    ocr_applied       INTEGER NOT NULL DEFAULT 0,
    ocr_engine        TEXT,
    page_count        INTEGER,
    source            TEXT NOT NULL DEFAULT 'upload',
    source_url        TEXT,
    ingested_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL DEFAULT 'default',
    ordinal           INTEGER NOT NULL,
    text              TEXT NOT NULL,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    embedding_json    TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_memory (
    tenant_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id, key)
);
