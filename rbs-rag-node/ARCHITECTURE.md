# RBS RAG Node.js — Architecture

## Overview

Node.js/TypeScript port of the TenBit RAG platform. Express.js server with Prisma ORM (SQLite) for relational storage, Qdrant for vector search, and a modular pipeline for document ingestion, hybrid retrieval, and LLM-powered answer generation.

---

## 1. System Topology

```
                                ┌──────────────────────┐
                                │    Express Server     │
                                │    (Port 3001)        │
                                │                      │
                                │  ┌────────────────┐  │
                                │  │  routes/index  │  │
                                │  │  (all REST +   │  │
                                │  │   SSE routes)  │  │
                                │  └───────┬────────┘  │
                                │          │           │
                                │  ┌───────▼────────┐  │
                                │  │   RagEngine     │  │
                                │  │  (orchestrator) │  │
                                │  └──┬───┬───┬───┬─┘  │
                                │     │   │   │   │     │
                                └─────┼───┼───┼───┼─────┘
                                      │   │   │   │
              ┌───────────────────────┼───┼───┼───┼───────────┐
              │                       │   │   │   │           │
              ▼                       ▼   ▼   ▼   ▼           │
     ┌──────────────┐    ┌──────────────┐    ┌────────────┐   │
     │    Qdrant     │    │   Prisma     │    │   Redis    │   │
     │  (Vector DB)  │    │  (SQLite)    │    │  (Cache)   │   │
     │  Port 6333    │    │  dev.db      │    │  (optional)│   │
     │  ANN + Cosine │    │  5 models    │    └────────────┘   │
     └──────────────┘    └──────────────┘                      │
                                                               │
     ┌─────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────┐
│                     External Services                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │  Gemini  │  │  OpenAI  │  │ Anthropic│  │  OCR Service │ │
│  │  (LLM +  │  │ (LLM +   │  │  (LLM)   │  │  (Port 8000) │ │
│  │  Embed)  │  │  Embed)  │  │          │  │              │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Module Architecture

### Source Layout (`src/`)

```
src/
├── index.ts              # Express app bootstrap, middleware, static files
├── config.ts             # AppConfig, tenantConfigFromRow, env-driven config
├── engine.ts             # RagEngine — central orchestrator
├── adminStore.ts         # AdminStore — tenant CRUD, activity logging
├── store.ts              # DbStore — Prisma document/chunk/session CRUD
├── vectorStore.ts        # QdrantVectorStore — HNSW ANN search, batch upsert
├── embeddings.ts         # Hash / OpenAI / Gemini embedding providers
├── chunking.ts           # HierarchicalChunker — heading split + sliding windows
├── llm.ts                # LLMClient — Gemini/OpenAI/Anthropic generate + stream
├── retrieval.ts          # HybridRetriever — dense + sparse + RRF + rerank
├── reranking.ts          # LocalReranker — term overlap + phrase bonus
├── validation.ts         # Retrieval validation & confidence scoring
├── documentLoaders.ts    # loadDocument for txt/md/html/csv/pdf
├── scraper.ts            # Web scraper — cheerio + WP REST API + crawl
├── ocrClient.ts          # OCR microservice HTTP client
├── providerPresets.ts    # Provider preset CRUD
├── seed.ts               # Demo tenant seeder
├── text.ts               # tokenize, cosineSimilarity, l2Normalize, bm25Scores
└── types/models.ts       # All TypeScript interfaces (Chunk, Answer, etc.)
```

### Dependency Flow

```
routes/index.ts
  └── RagEngine (engine.ts)
        ├── DbStore (store.ts) ─────── Prisma ────── SQLite
        ├── AdminStore (adminStore.ts) ── Prisma ── SQLite
        ├── QdrantVectorStore (vectorStore.ts) ── Qdrant
        ├── EmbeddingProvider (embeddings.ts)
        │     ├── HashEmbeddingProvider
        │     ├── OpenAIEmbeddingProvider
        │     └── GeminiEmbeddingProvider
        ├── HierarchicalChunker (chunking.ts)
        ├── LLMClient (llm.ts)
        │     ├── generateGemini / generateGeminiStream
        │     ├── generateOpenAI / generateOpenAIStream
        │     └── generateAnthropic
        └── HybridRetriever (retrieval.ts)
              ├── QdrantVectorStore.search()
              ├── DbStore.listChunks() (fallback)
              ├── bm25Scores() (text.ts)
              └── LocalReranker.rerank() (reranking.ts)
```

---

## 3. Data Flow

### Ingestion Pipeline

```
Upload File / Scrape / Cloud Sync
        │
        ▼
  Document Loader (loadDocument)
        │  .txt  → direct read
        │  .md   → direct read
        │  .html → direct read
        │  .csv  → direct read
        │  .pdf  → pdf-parse → OCR fallback
        │
        ▼
  HierarchicalChunker.chunk()
        │  Split by headings (H1-H6)
        │  Sliding token windows (320 tokens, 48 overlap)
        │  Metadata: section, document_name, tenant_id, kb_id
        │
        ▼
  EmbeddingProvider.embed()
        │  Hash / OpenAI / Gemini
        │
        ├──▶ DbStore.upsertDocument() + upsertChunks()
        └──▶ QdrantVectorStore.upsertChunks()
```

### Query Pipeline

```
User Query
    │
    ▼
RagEngine.ask() / askStream()
    │
    ├── 1. HybridRetriever.search()
    │       ├── a. Embed query (EmbeddingProvider)
    │       ├── b. Qdrant ANN search (topK * 2)
    │       ├── c. Fallback: SQLite + local cosine sim
    │       ├── d. BM25 sparse scoring
    │       ├── e. RRF fusion (0.55 dense + 0.45 sparse)
    │       ├── f. Rerank (LocalReranker)
    │       └── g. Return results + RetrievalProfile
    │
    ├── 2. Load session memory from SQLite
    │
    ├── 3. Build RAG messages (system prompt + context + memory)
    │
    ├── 4. LLM generate (sync or async SSE stream)
    │
    ├── 5. Store conversation turn in SQLite
    │
    └── 6. Return Answer (text, citations, validation, profile)
```

---

## 4. Multi-Tenant Isolation

```
admin.db (Prisma SQLite — global)
  └── tenants table
        ├── tenantId: "acme-corp"
        ├── apiKey: "rbs_rag_sk_<hex>" (unique, hashed)
        ├── llmProvider: "gemini", llmApiKey: "AIza..."
        ├── embeddingProvider: "hash"
        ├── retrieval: topK=20, denseWeight=0.55
        └── chunking: maxTokens=320, overlapTokens=48

tenants/{tenantId}/
  ├── documents/
  │     ├── policy.pdf
  │     └── scraped_example_com.txt
  └── (SQLite via Prisma: documents, chunks, session_turns filtered by tenantId)

Qdrant: collection "rag_chunks" with payload fields:
  - tenant_id, knowledge_base_id, document_id, document_name
  - Queries filtered by knowledge_base_id for isolation
```

### Tenant Request Lifecycle

```
Request: POST /api/v1/chat
Headers: X-API-Key: rbs_rag_sk_tenantA_xxx
Body: { "query": "What is the refund policy?" }

1. resolveClientTenant middleware
   └── AdminStore.getTenantByApiKey(apiKey)
       └── Returns tenant: { tenantId: "tenantA", llmProvider: "gemini", ... }

2. getOrCreateEngine(tenant)
   └── createEngineFromTenant(tenant, rootDir, store, adminStore)
       └── RagEngine with tenantA's config (LLM key, embedding, retrieval params)
       └── Cached in Map<string, RagEngine>

3. RagEngine.ask()
   └── HybridRetriever.search(query, kbId="default", tenantId="tenantA")
       └── Qdrant search filtered by knowledge_base_id
       └── SQLite queries filtered by tenantId
   └── LLM call uses tenantA's API key + provider
   └── Session turns stored with tenantId="tenantA"

4. Response: Only tenantA's data accessible
```

---

## 5. Database Schema (Prisma — SQLite)

### Models

```
Tenant
├── tenantId (PK), name, apiKey (unique), status, subscriptionTier
├── llmProvider, llmModel, llmApiKey, llmBaseUrl
├── embeddingProvider, embeddingModel, embeddingDimensions, embeddingBaseUrl, embeddingApiKey
├── retrievalTopK, retrievalRerankTopK, retrievalFinalContextK
├── retrievalDenseWeight, retrievalSparseWeight
├── chunkingMaxTokens, chunkingOverlapTokens, chunkingSemantic, chunkingSemanticThreshold
├── rerankerType, sessionMemoryLimit, chatRetentionDays, systemPrompt
├── createdAt, updatedAt
└── relations: documents, chunks, sessionTurns, activityLogs

Document
├── documentId (PK), tenantId (FK), knowledgeBaseId
├── path, name, documentType, text, metadataJson, ocrApplied, ocrEngine, pageCount, source, sourceUrl, ingestedAt
└── relations: tenant, chunks

Chunk
├── chunkId (PK), documentId (FK), tenantId (FK), knowledgeBaseId
├── ordinal, text, metadataJson, embeddingJson
└── relations: document, tenant

SessionTurn
├── id (PK, autoincrement), tenantId (FK), sessionId, userId, role, content, createdAt
└── relation: tenant

ActivityLog
├── id (PK, autoincrement), tenantId (FK, nullable), level, operation, message, details, traceback, createdAt
└── relation: tenant
```

---

## 6. LLM Routing (`llm.ts`)

Multi-provider support with auto-detection:

| Provider | Detection | Client Method |
|---|---|---|
| **Gemini** | API key `AIza...` or model `gemini-*` | `@google/generative-ai` SDK |
| **OpenAI / Compatible** | Default catch-all | `fetch` → `/v1/chat/completions` |
| **Anthropic** | Key `sk-ant...` or URL `anthropic.com` | `fetch` → `api.anthropic.com` |
| **Mistral** | Provider `mistral` | OpenAI-compatible client |
| **Ollama** | OpenAI-compatible base URL | OpenAI-compatible client |

Features:
- Fallback chain: primary model → `fallbackModels` on retryable errors (429, 503, UNAVAILABLE, timeout)
- Streaming: async generators returning `StreamingChunk` objects
- Response cleaning: strips HTML tags, broken tags, normalizes whitespace

---

## 7. Qdrant Integration (`vectorStore.ts`)

- **Client**: `@qdrant/js-client-rest` with `checkCompatibility: false`
- **Collection**: `rag_chunks` with COSINE distance, configurable vector size (default 384)
- **Point ID**: UUID v5 derived from chunk ID for deterministic mapping
- **Payload**: `chunk_id`, `document_id`, `text`, `ordinal` + all metadata fields
- **Batch Operations**: Upserts in groups of 64
- **Graceful Degradation**: All API calls wrapped in try-catch; `initialized` flag gates all operations
- **Filtering**: `knowledge_base_id` and arbitrary metadata field matching via `buildFilter()`

---

## 8. Web Scraper Architecture (`scraper.ts`)

```
scrapeUrl(request, tenantDir)
  │
  ├── validateUrl() — blocks private/internal networks
  │
  ├── fetchUrl() — native fetch + curl fallback (Cloudflare bypass)
  │
  ├── scrapeSinglePage()
  │     ├── extractContent() — cheerio article selectors
  │     ├── extractJsonLd() — JSON-LD from <script> tags
  │     └── fetchWordPressContent() — WP REST API fallback
  │
  ├── crawlPages() — BFS queue, domain filter, depth limit
  │     (if crawl=true or fullSite=true)
  │
  └── Save as {site}_{title}_{type}_{jobId}.txt in tenant docs dir
```

### Fetch Strategy
1. Native `fetch` with browser-like headers (User-Agent, Accept, Referer)
2. On 403/503 with Cloudflare challenge → `curl` subprocess with same headers
3. Content extraction via cheerio with prioritized article selectors

---

## 9. Config System (`config.ts`)

### Global Config (`.env`)
| Variable | Default | Description |
|---|---|---|
| `PORT` | `3001` | Server port |
| `LLM_PROVIDER` | `gemini` | Default LLM provider |
| `LLM_API_KEY` | — | Default LLM key |
| `LLM_MODEL` | `gemini-2.5-flash-lite` | Default model |
| `EMBEDDING_PROVIDER` | `hash` | Embedding provider |
| `EMBEDDING_DIMENSIONS` | `384` | Vector dimensions |
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `ADMIN_PASSWORD` | `admin` | Dashboard password |
| `ADMIN_JWT_SECRET` | — | JWT signing secret |
| `DATABASE_URL` | `file:./dev.db` | SQLite path |
| `RATE_LIMIT_RPM` | `60` | Requests/minute |

### Per-Tenant Config (via `tenantConfigFromRow`)
Each tenant row in Prisma stores independent config for LLM, embeddings, retrieval, chunking, reranker, session memory. Overrides global defaults at runtime.

---

## 10. Request Lifecycle (End-to-End Example)

### Ingestion Request
```
POST /api/v1/tenants/acme-corp/ingest
Authorization: Bearer <admin-jwt>

1. requireAdmin middleware → verify JWT
2. AdminStore.getTenant("acme-corp") → tenant config
3. getOrCreateEngine(tenant) → create/cache RagEngine
4. engine.ingest("acme-corp", "default", applyOcr=false)
   ├── Iterate documents in tenants/acme-corp/documents/
   ├── loadDocument() per file (txt/md/html/csv/pdf)
   ├── HierarchicalChunker.chunk() → Chunk[]
   ├── EmbeddingProvider.embed() → number[][]
   ├── DbStore.upsertDocument() + upsertChunks()
   └── QdrantVectorStore.upsertChunks()
5. Return IngestSummary { documents, chunks, skipped, errors }
```

### Chat Request (SSE Streaming)
```
POST /api/v1/tenants/acme-corp/chat/stream
Authorization: Bearer <admin-jwt>
Body: { "query": "What is the refund policy?", "session_id": "sess-1" }

1. requireAdmin → verify JWT
2. AdminStore.getTenant("acme-corp") → tenant config
3. getOrCreateEngine(tenant) → cached RagEngine
4. engine.askStream(query, "default", "sess-1", "web-user")
   ├── HybridRetriever.search() → ranked chunks + profile
   ├── DbStore.getSessionMemory() → past turns
   ├── buildRagMessages() → system + context + memory + query
   ├── LLMClient.generateStream() → async generator
   │     └── SSE: data: {"text":"The refund...","done":false}
   ├── DbStore.addSessionTurn() (user + assistant)
   └── SSE: data: {"text":"","done":true,"citations":[...]}
5. Client receives SSE stream in real-time
```
