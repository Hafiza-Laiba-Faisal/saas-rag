-- CreateTable
CREATE TABLE "tenants" (
    "tenant_id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "api_key" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'active',
    "subscription_tier" TEXT NOT NULL DEFAULT 'basic',
    "monthly_fee" REAL NOT NULL DEFAULT 299.0,
    "llm_provider" TEXT NOT NULL DEFAULT 'gemini',
    "llm_model" TEXT NOT NULL DEFAULT 'gemini-2.5-flash-lite',
    "llm_api_key" TEXT NOT NULL,
    "llm_base_url" TEXT,
    "embedding_provider" TEXT NOT NULL DEFAULT 'hash',
    "embedding_model" TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    "embedding_dimensions" INTEGER NOT NULL DEFAULT 384,
    "embedding_base_url" TEXT,
    "embedding_api_key" TEXT,
    "retrieval_top_k" INTEGER NOT NULL DEFAULT 20,
    "retrieval_rerank_top_k" INTEGER NOT NULL DEFAULT 8,
    "retrieval_final_context_k" INTEGER NOT NULL DEFAULT 5,
    "retrieval_dense_weight" REAL NOT NULL DEFAULT 0.55,
    "retrieval_sparse_weight" REAL NOT NULL DEFAULT 0.45,
    "chunking_max_tokens" INTEGER NOT NULL DEFAULT 320,
    "chunking_overlap_tokens" INTEGER NOT NULL DEFAULT 48,
    "chunking_semantic" BOOLEAN NOT NULL DEFAULT false,
    "chunking_semantic_threshold" REAL NOT NULL DEFAULT 0.75,
    "reranker_type" TEXT NOT NULL DEFAULT 'local',
    "session_memory_limit" INTEGER NOT NULL DEFAULT 8,
    "chat_retention_days" INTEGER NOT NULL DEFAULT 30,
    "system_prompt" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "documents" (
    "document_id" TEXT NOT NULL PRIMARY KEY,
    "tenant_id" TEXT NOT NULL,
    "knowledge_base_id" TEXT NOT NULL DEFAULT 'default',
    "path" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "document_type" TEXT NOT NULL,
    "text" TEXT NOT NULL,
    "metadata_json" TEXT NOT NULL DEFAULT '{}',
    "ocr_applied" BOOLEAN NOT NULL DEFAULT false,
    "ocr_engine" TEXT,
    "page_count" INTEGER,
    "source" TEXT NOT NULL DEFAULT 'upload',
    "source_url" TEXT,
    "ingested_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "documents_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "tenants" ("tenant_id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "chunks" (
    "chunk_id" TEXT NOT NULL PRIMARY KEY,
    "document_id" TEXT NOT NULL,
    "tenant_id" TEXT NOT NULL,
    "knowledge_base_id" TEXT NOT NULL DEFAULT 'default',
    "ordinal" INTEGER NOT NULL,
    "text" TEXT NOT NULL,
    "metadata_json" TEXT NOT NULL DEFAULT '{}',
    "embedding_json" TEXT NOT NULL DEFAULT '[]',
    CONSTRAINT "chunks_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "chunks_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "tenants" ("tenant_id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "session_turns" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "tenant_id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "user_id" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "session_turns_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "tenants" ("tenant_id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "activity_logs" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "tenant_id" TEXT,
    "level" TEXT NOT NULL DEFAULT 'INFO',
    "operation" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "details" TEXT,
    "traceback" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "activity_logs_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "tenants" ("tenant_id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "tenants_api_key_key" ON "tenants"("api_key");
