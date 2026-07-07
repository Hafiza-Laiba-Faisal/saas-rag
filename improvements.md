# Enterprise Production-Grade Improvement Plan — TenBit RAG

This document maps **every module in the codebase** against the [rag.docx](file:///c:/Root/Projects/TenBit/RAG/rag.docx) recommended production stack, identifies gaps, and proposes concrete improvements.

---

## RAG Document: Recommended Production Stack vs Current Implementation

| RAG Doc Recommendation                                      | Current Implementation                                          | Status             | Gap Severity |
| ----------------------------------------------------------- | --------------------------------------------------------------- | ------------------ | ------------ |
| **Qdrant** vector database                            | SQLite with JSON-serialized embeddings + brute-force cosine sim | ❌ Not Implemented | 🔴 Critical  |
| **BGE-M3** embeddings (dense + sparse + multi-vector) | HashEmbeddingProvider (deterministic hash, not semantic)        | ❌ Not Implemented | 🔴 Critical  |
| **BGE Reranker** (cross-encoder)                      | Word-overlap heuristic (`LocalReranker`)                      | ❌ Not Implemented | 🔴 Critical  |
| **Semantic Chunking**                                 | Only hierarchical heading-based chunking                        | 🟡 Partial         | 🟠 High      |
| **OCR Processing**                                    | Not implemented                                                 | ❌ Not Implemented | 🟠 High      |
| **Token Streaming**                                   | Synchronous full-response only                                  | ❌ Not Implemented | 🟠 High      |
| **Metadata Enrichment**                               | Basic (name, type, section) — missing 13+ recommended fields   | 🟡 Partial         | 🟡 Medium    |
| **Hybrid Search** (dense + sparse)                    | Implemented in Python loops                                     | 🟡 Works but O(n)  | 🟠 High      |
| **ElasticSearch** (optional)                          | Not implemented                                                 | ⬜ Optional        | ⚪ Low       |
| **Hierarchical Chunking**                             | ✅ Heading-aware sectioning                                     | ✅ Implemented     | ✅ OK        |
| **Token Boundary Enforcement**                        | ✅ Word-count windows with overlap                              | ✅ Implemented     | ✅ OK        |
| **Session Memory**                                    | ✅ SQLite-backed conversation turns                             | ✅ Implemented     | ✅ OK        |
| **User Memory**                                       | ✅ Key-value per user per tenant                                | ✅ Implemented     | ✅ OK        |
| **Self-RAG Validation**                               | ✅ Basic confidence scoring                                     | 🟡 Simplistic      | 🟡 Medium    |
| **Citation Generation**                               | ✅ Chunk-level citations                                        | ✅ Implemented     | ✅ OK        |
| **Agentic RAG**                                       | ✅ API keys + widget embed                                      | ✅ Implemented     | ✅ OK        |
| **Multi-Tenant Isolation**                            | ✅ Separate DB + folder per tenant                              | ✅ Implemented     | ✅ OK        |

---

## Improvement Categories

### 🔴 CRITICAL — Core Architecture Upgrades

---

#### 1. Migrate Vector Storage to Qdrant

**Current**: [store.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/store.py) — All chunks stored as SQLite rows with `embedding_json TEXT` (JSON-serialized float arrays). Search does full-table scan.

**Problem**:

- O(n) brute-force search on every query
- Embeddings stored as JSON text strings (parsing overhead)
- No ANN (Approximate Nearest Neighbor) index
- No hardware acceleration (SIMD/AVX)
- Cannot scale past ~5,000 chunks without noticeable latency

**Improvement**:

- Create `QdrantRagStore` that stores embeddings + chunk text + metadata in Qdrant collections
- One Qdrant collection per tenant (isolation)
- Use HNSW index with quantization for sub-10ms vector search
- Keep SQLite for session turns, user memory, document registry (non-vector data)
- Support both embedded Qdrant (dev) and remote Qdrant server (production)

**Files to modify**:

- `[NEW]` `src/rbs_rag/vector_store.py` — Qdrant vector store abstraction
- `[MODIFY]` [store.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/store.py) — Split into relational store + vector store
- `[MODIFY]` [retrieval.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/retrieval.py) — Query Qdrant instead of loading all chunks
- `[MODIFY]` [engine.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/engine.py) — Initialize Qdrant store
- `[MODIFY]` [config.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/config.py) — Add Qdrant connection settings
- `[MODIFY]` [server.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/server.py) — Ingestion writes to Qdrant

---

#### 2. Upgrade Embeddings to BGE-M3 (or Equivalent Production Embedder)

**Current**: [embeddings.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/embeddings.py) — Default is `HashEmbeddingProvider` which hashes tokens into a sparse vector. This is **not semantic** — it cannot understand meaning, synonyms, or context.

**Problem**:

- Hash embeddings have **zero semantic understanding**
- "Annual Revenue" and "Yearly Income" would get completely different vectors
- The RAG doc explicitly recommends **BGE-M3** for its dense + sparse + multi-vector capabilities
- Current cloud embedding options (OpenAI, Gemini) add latency and cost per query

**Improvement**:

- Add `BGE-M3` support via `FlagEmbedding` or `sentence-transformers` library
- BGE-M3 produces both **dense** and **sparse** vectors natively — can replace BM25
- Offer tiered embedding options:
  - **Local BGE-M3** (best quality, requires GPU/CPU model download ~1.5GB)
  - **Cloud Embeddings** (OpenAI/Gemini — already supported)
  - **Hash Embeddings** (keep as dev-mode fallback only)
- Qdrant supports storing both dense and sparse vectors in the same point

**Files to modify**:

- `[MODIFY]` [embeddings.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/embeddings.py) — Add BGE-M3 provider
- `[MODIFY]` [config.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/config.py) — Add embedding tier config

---

#### 3. Replace Heuristic Reranker with BGE Reranker (Cross-Encoder)

**Current**: [reranking.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/reranking.py) — `LocalReranker` uses word-overlap ratio + phrase-match bonus. This is a **lexical heuristic**, not a cross-encoder.

**Problem**:

- Word overlap misses semantic relevance (e.g., "car" vs "vehicle" gets 0 overlap)
- No learned ranking signal — purely string matching
- The RAG doc specifically recommends **BGE Reranker** cross-encoder

**Improvement**:

- Add `BGEReranker` using `FlagEmbedding` or `sentence-transformers` cross-encoder
- Cross-encoder scores (query, chunk) pairs with a trained model
- Keep `LocalReranker` as fallback for environments without GPU/model

**Files to modify**:

- `[MODIFY]` [reranking.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/reranking.py) — Add cross-encoder reranker
- `[MODIFY]` [config.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/config.py) — Add reranker config

---

### 🟠 HIGH — Pipeline & Quality Improvements

---

#### 4. Add Semantic Chunking Layer

**Current**: [chunking.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/chunking.py) — `HierarchicalChunker` splits by markdown headings + token windows. No semantic analysis.

**Problem**:

- Chunks can split mid-topic if paragraphs happen to cross the token boundary
- No understanding of topic boundaries within a section
- The RAG doc lists "Semantic Chunking" as a required layer

**Improvement**:

- Add semantic similarity-based boundary detection between paragraphs
- Use embedding cosine similarity to detect topic shifts within a section
- Pipeline: Hierarchical split → Semantic split → Token boundary enforcement
- This produces chunks that are both structurally and semantically coherent

**Files to modify**:

- `[MODIFY]` [chunking.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/chunking.py) — Add semantic boundary detection

---

#### 5. Add Token Streaming (SSE) for LLM Responses

**Current**: [llm.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/llm.py) — All LLM clients use synchronous `_post_json()` which waits for the entire response before returning. User sees nothing for 10-50+ seconds.

**Problem**:

- Terrible UX — user stares at a loading spinner for the entire LLM generation time
- The RAG doc explicitly lists "Token Streaming" as a response layer requirement
- For large responses, this can be 30-60 seconds of dead time

**Improvement**:

- Add Server-Sent Events (SSE) streaming endpoint
- Modify LLM clients to yield tokens via `stream=True`
- Frontend receives tokens in real-time as they're generated
- Keep non-streaming endpoint as fallback for widget/API integration

**Files to modify**:

- `[MODIFY]` [llm.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/llm.py) — Add `generate_stream()` method
- `[MODIFY]` [server.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/server.py) — Add SSE streaming chat endpoint
- `[MODIFY]` `index.html` — Frontend SSE consumer for real-time token display

---

#### 6. Add OCR Processing for Scanned PDFs

**Current**: [document_loaders.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/document_loaders.py) — PDF parsing uses `pypdf` text extraction. Scanned/image PDFs extract zero text.

**Problem**:

- Scanned documents, photographed pages, and image-heavy PDFs are silently ignored
- The RAG doc lists "OCR Processing" as a pipeline step

**Improvement**:

- Detect when `pypdf` extracts empty/minimal text from a PDF page
- Fall back to OCR using `pytesseract` + `pdf2image` or `easyocr`
- Add image extraction from PDFs for visual content

**Files to modify**:

- `[MODIFY]` [document_loaders.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/document_loaders.py) — Add OCR fallback
- `[MODIFY]` `pyproject.toml` — Add OCR optional dependency

---

#### 7. Enrich Metadata Extraction

**Current**: [document_loaders.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/document_loaders.py#L36-L42) — Only extracts: `document_name`, `document_type`, `source_path`.

**RAG doc recommends 20 metadata fields**:

```
Tenant ID, Knowledge Base ID, Document ID, Document Name, Document Type,
Department, Country, Region, Language, Author, Version, Creation Date,
Modification Date, Upload Date, Page Number, Section, Subsection,
Tags, Access Level
```

**Improvement**:

- Extract author, creation date, modification date from DOCX/PDF metadata headers
- Auto-detect language using character-set analysis
- Add page number tracking per chunk for PDFs
- Allow user-provided tags and department via upload form
- Store all metadata in Qdrant payload for filtered retrieval

**Files to modify**:

- `[MODIFY]` [document_loaders.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/document_loaders.py) — Extract rich metadata
- `[MODIFY]` [chunking.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/chunking.py) — Propagate page numbers
- `[MODIFY]` [server.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/server.py) — Accept metadata in upload API

---

### 🟡 MEDIUM — Reliability & Accuracy Improvements

---

#### 8. Improve Self-RAG Validation

**Current**: [validation.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/validation.py) — 18 lines of code. Checks only score thresholds (0.08, 0.25) and result count.

**Problem**:

- No evidence verification (does the answer actually cite the retrieved chunks?)
- No grounding verification (is the LLM hallucinating beyond the context?)
- No retrieval sufficiency check beyond count
- The RAG doc lists 4 validation responsibilities: Evidence Verification, Retrieval Sufficiency Check, Grounding Verification, Answer Confidence Assessment

**Improvement**:

- Add post-generation grounding check: compare answer claims against retrieved chunks
- Add multi-signal confidence: combine score distribution, chunk diversity, query coverage
- Add answer-context alignment scoring
- Log validation results to audit trail for quality monitoring

**Files to modify**:

- `[MODIFY]` [validation.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/validation.py) — Expand validation logic
- `[MODIFY]` [engine.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/engine.py) — Post-generation validation

---

#### 9. Add Async Architecture for Concurrent Requests

**Current**: All endpoints are synchronous. `RagEngine` is instantiated per-request. SQLite connections are opened/closed per operation.

**Problem**:

- Every chat request blocks the server thread during LLM generation (10-50s)
- Only one request can be processed at a time per worker
- No connection pooling for database or Qdrant
- `urllib.request` is synchronous and blocking

**Improvement**:

- Use `httpx` (async HTTP client) instead of `urllib.request` for LLM API calls
- Make chat endpoints `async`
- Add connection pooling for Qdrant client
- Cache `RagEngine` instances per tenant instead of recreating each request

**Files to modify**:

- `[MODIFY]` [llm.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/llm.py) — Async HTTP with `httpx`
- `[MODIFY]` [server.py](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/server.py) — Async endpoints + engine caching
- `[MODIFY]` `pyproject.toml` — Add `httpx` dependency

---

#### 10. Add Rate Limiting, Request Queuing & Retry Logic

**Current**: No rate limiting. LLM API calls have basic fallback models but no exponential backoff. No request queuing.

**Problem**:

- A single abusive tenant can exhaust the entire system's LLM API quota
- No protection against API rate limits (429 errors)
- No retry with exponential backoff for transient failures
- No request priority queuing

**Improvement**:

- Add per-tenant rate limiting (configurable by subscription tier)
- Add exponential backoff with jitter for LLM API retries
- Add request queue for concurrent users
- Log rate-limit events to audit trail

---

#### 11. Security Hardening

**Current issues identified**:

- API keys stored in plaintext in SQLite ([admin_db.py:30](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/admin_db.py#L30))
- No input sanitization on LLM prompts (prompt injection risk)
- Terminal command execution endpoint with minimal filtering ([server.py:865](file:///c:/Root/Projects/TenBit/RAG/src/rbs_rag/web/server.py#L865))
- No CORS policy configured
- No authentication on admin dashboard
- Session IDs are user-provided strings (no validation)

**Improvement**:

- Encrypt API keys at rest (AES-256 or use OS keyring)
- Add prompt injection detection/filtering
- Restrict terminal endpoint to safe commands only or remove it
- Add CORS middleware configuration
- Add admin authentication (API key or JWT)
- Add session ID validation and sanitization

---

### ⚪ NICE-TO-HAVE — Polish & Performance

---

#### 12. Add Document De-duplication

Currently the same document can be uploaded multiple times, creating duplicate chunks. Add content-hash based de-duplication to skip re-ingestion of identical files.

#### 13. Add Chunk-Level Caching

Cache embedding computations and frequently-queried results using LRU cache to reduce API calls and computation.

#### 14. Add Health Check & Monitoring Endpoints

Add `/health`, `/ready`, `/metrics` endpoints for production monitoring, load balancer health checks, and Prometheus-compatible metrics.

#### 15. Add Support for More Document Formats

Current: `.txt`, `.md`, `.html`, `.docx`, `.pdf`
Add: `.xlsx`, `.csv`, `.pptx`, `.json`, `.xml`, `.epub`

#### 16. Add Knowledge Base Management

Currently everything goes into a single "default" knowledge base per tenant. Add full KB CRUD with UI support for multiple knowledge bases per tenant.

---

## Proposed Implementation Order

> [!IMPORTANT]
> Recommended execution sequence based on impact and dependency chain:

| Phase                                    | Items                                        | Estimated Effort     |
| ---------------------------------------- | -------------------------------------------- | -------------------- |
| **Phase 1: Vector Infrastructure** | 1. Qdrant Migration + 2. BGE-M3 Embeddings   | Major (~2-3 days)    |
| **Phase 2: Retrieval Quality**     | 3. BGE Reranker + 4. Semantic Chunking       | Moderate (~1-2 days) |
| **Phase 3: UX & Streaming**        | 5. Token Streaming (SSE)                     | Moderate (~1 day)    |
| **Phase 4: Data Pipeline**         | 6. OCR + 7. Metadata Enrichment              | Moderate (~1-2 days) |
| **Phase 5: Reliability**           | 8. Self-RAG + 9. Async + 10. Rate Limiting   | Moderate (~1-2 days) |
| **Phase 6: Security**              | 11. Security Hardening                       | Moderate (~1 day)    |
| **Phase 7: Polish**                | 12-16. De-dup, Caching, Health, Formats, KBs | Ongoing              |

---

## Open Questions

1. **QdrantQdrandeployment mode**: Do you want Qdrant running as a Docker container (production) or embedded in-memory (simpler for dev)? I can support both with a config toggle.
2. **BGE-M3 vs cloud embeddings**: BGE-M3 requires downloading a ~1.5GB model and runs locally. Do you have a machine with sufficient resources? Or should we use a cloud embedding API (OpenAI/Gemini) as the production embedder with Qdrant?
3. **BGE Reranker**: Same question — local model (~450MB) or cloud reranking API?
4. **Token streaming priority**: Should I prioritize SSE streaming in Phase 1 alongside Qdrant, since the current 50s response time is the most visible UX issue?
5. **Security scope**: The terminal command execution endpoint is a significant attack surface. Should it be removed entirely in production, or restricted to admin-only with authentication?
6. **Phase execution**: Should I start with Phase 1 (Qdrant + BGE-M3) immediately, or do you want to review/modify this plan first?
