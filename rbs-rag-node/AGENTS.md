# RAG Node.js Project Context

## Project Goal
Rewrite the entire Python RAG application (`src/rbs_rag/`) to Node.js/TypeScript in `rbs-rag-node/`. Exact API parity so dashboard/widget work without changes.

## Completed

### Core Infrastructure
- Express.js + TypeScript (ESM, strict mode) — compiles with zero errors via `tsc --noEmit`
- Prisma ORM with SQLite — 5 models: Tenant, Document, Chunk, SessionTurn, ActivityLog
- Migration `20260717052307_init` applied, `dev.db` created and seeded
- Dockerfile (multi-stage) + docker-compose.node.yml (rag-node + qdrant)

### Modules Ported (all in `src/`)
- `config.ts` — env-driven config with per-tenant override via `tenantConfigFromRow()`
- `types/models.ts` — all DTOs (Chunk, SearchResult, Answer, StreamingChunk, Citation, etc.)
- `text.ts` — tokenize, cosineSimilarity, l2Normalize, bm25Scores
- `embeddings.ts` — HashEmbeddingProvider, OpenAIEmbeddingProvider, GeminiEmbeddingProvider + factory
- `vectorStore.ts` — QdrantVectorStore with graceful fallback when Qdrant unavailable (all API calls wrapped in try-catch)
- `chunking.ts` — HierarchicalChunker (sections → sliding-window token windows with overlap)
- `llm.ts` — LLMClient (generate + generateStream) for Gemini/OpenAI/Anthropic; `_clean_llm_text()` 
- `reranking.ts` — LocalReranker with query-term overlap + phrase bonus
- `retrieval.ts` — HybridRetriever (dense + sparse fusion + reranking) with RetrievalProfile
- `validation.ts` — validateRetrieval + validateStreamingAnswer
- `documentLoaders.ts` — loadDocument for .txt, .md, .html, .csv, .pdf
- `store.ts` — DbStore (Prisma): document/chunk CRUD, session memory, expiry
- `adminStore.ts` — AdminStore: tenant CRUD, activity logging, cascading delete
- `engine.ts` — RagEngine: ingest (files→chunks→embeddings→store), ask (retrieve→LLM→store), askStream (SSE)
- `scraper.ts` — Real scraper (cheerio-based + WordPress REST API fallback). Validates URL, fetches, extracts title/description/text, saves as `scraped_<uuid>.txt` in tenant documents dir. Supports `crawl`/`fullSite` for multi-page scraping.
- `seed.ts` — Creates demo tenant with `rbs_rag_sk_*` API key
- `routes/index.ts` — All Express routes: admin auth (JWT), tenant CRUD, document list/view/upload/delete, ingestion start/status, chat (non-streaming + SSE), client chat, client document CRUD, system status/logs, sessions, scrape (real, not placeholder)

### Entry Point
- `src/index.ts` — Express app with helmet (CSP disabled via `contentSecurityPolicy: false`), CORS `*`, compression, 50mb JSON limit, static files (index.html, client.html, widget.html)

## Known Issues & Fixes Applied

1. **Qdrant unavailable crashes server** → Fixed: all QdrantVectorStore methods wrap API calls in try-catch; `engine.initialize()` wrapped in try-catch; `checkCompatibility: false` in constructor
2. **CSP blocks inline scripts** → Fixed: `helmet({ contentSecurityPolicy: false })`
3. **DATABASE_URL not set** → Fixed: hardcoded default `file:./dev.db` in `index.ts`
4. **ADMIN_JWT_SECRET empty** → Fixed: default value in `.env`
5. **Prisma raw query + SQLite array error** → Fixed: replaced `$executeRawUnsafe` with `prisma.chunk.deleteMany` in `store.ts:21`
6. **start-dev.sh screen multiplexer confusing** → Replaced `screen` with background processes + log files (`.logs/server.log`)
7. **Scraper failed on JS-rendered sites (WordPress/WPBakery)** → Fixed: added WordPress REST API fallback with shortcode/HTML stripping, JSON-LD extraction, and deep crawl support (`crawl`, `fullSite`, `maxPages`, `maxDepth` params)

## Scripts

| Command | Purpose |
|---|---|
| `npm run setup` | Prisma generate + migrate (one-time) |
| `npm run build` | tsc compile |
| `npm start` | `node dist/index.js` |
| `npm run dev` | `tsx watch src/index.ts` (auto-restart) |
| `npm run seed` | `tsx src/seed.ts` — creates demo tenant |
| `./scripts/start-dev.sh` | Kills old processes, starts Qdrant (Docker), runs setup + seed, builds, starts server in background, writes logs to `.logs/server.log` |
| `./scripts/stop-dev.sh` | Kills server and Qdrant container |

## How to Run

```bash
cd rbs-rag-node
./scripts/start-dev.sh
```

Server runs in background. View logs: `tail -f .logs/server.log`.  
Stop: `./scripts/stop-dev.sh`.

## API Endpoints (all under `/api/v1`)

- `POST /admin/login` — auth (username/password → JWT)
- `GET /tenants` — list tenants (admin)
- `POST /tenants` — create tenant
- `GET /tenants/:id` — tenant detail
- `PUT /tenants/:id` — update tenant
- `DELETE /tenants/:id` — delete tenant + cascade
- `GET /tenants/:id/documents` — list documents
- `POST /tenants/:id/upload` — upload document
- `GET /tenants/:id/documents/:filename` — view document
- `DELETE /tenants/:id/documents/:filename` — delete document
- `POST /tenants/:id/ingest` — start ingestion
- `POST /tenants/:id/chat` — non-streaming chat
- `POST /tenants/:id/chat/stream` — SSE streaming chat
- `POST /tenants/:id/scrape` — scrape URL → save as document. Params: `crawl` (bool), `full_site` (bool), `max_pages`, `max_depth`
- `GET /tenants/:id/sessions` — list sessions
- `DELETE /tenants/:id/sessions` — purge expired sessions
- `GET /system/status` — system stats
- `GET /system/logs` — activity logs
- `POST /chat` — client chat (X-API-Key header)
- `POST /chat/stream` — client streaming chat
- `GET /client/documents` — client document list
- `POST /client/scrape` — client scrape

## Database
- SQLite file: `rbs-rag-node/dev.db` (or `prisma/dev.db` depending on DATABASE_URL)
- Prisma schema: `rbs-rag-node/prisma/schema.prisma`

## .env File (`rbs-rag-node/.env`)
- `LLM_API_KEY` — your Gemini/OpenAI/Anthropic key (placeholder: `your-gemini-api-key`)
- `QDRANT_HOST` / `QDRANT_PORT` — Qdrant connection
- `ADMIN_PASSWORD=admin` / `ADMIN_JWT_SECRET=change-me-...`
- `DATABASE_URL=file:./dev.db`
- `PORT=3001`
