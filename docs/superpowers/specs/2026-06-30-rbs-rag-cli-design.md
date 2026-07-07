# RBS RAG CLI Foundation Design

## Goal

Build a complete CLI-first RAG foundation that can run independently today and be reused later inside web, SaaS, or dedicated-company products with minimal changes.

## Architecture

The project exposes a command-line interface over a reusable Python package. The CLI contains only input/output handling; ingestion, retrieval, reranking, memory, validation, and LLM generation live in service modules that a future UI or API can call directly.

The first working implementation uses local storage, local embeddings, local reranking, and API-based LLM generation. The local implementation is dependency-light so the CLI can be tested immediately. Production adapters can swap in stronger components such as Qdrant and BGE/FastEmbed without changing the CLI surface.

## Core Components

- `rbs_rag.config`: configuration loading, environment expansion, and project initialization.
- `rbs_rag.document_loaders`: TXT, Markdown, HTML, DOCX, and optional PDF text extraction.
- `rbs_rag.chunking`: hierarchical paragraph/heading splitting, semantic-style grouping, and token boundary enforcement.
- `rbs_rag.embeddings`: local deterministic embeddings for a zero-service baseline, with optional stronger local embedding providers later.
- `rbs_rag.store`: local SQLite persistence for documents, chunks, embeddings, and memory.
- `rbs_rag.retrieval`: metadata-aware dense and sparse retrieval with hybrid score fusion.
- `rbs_rag.reranking`: local reranking over retrieved candidates.
- `rbs_rag.memory`: session and user memory persistence.
- `rbs_rag.validation`: retrieval sufficiency and grounding checks before final generation.
- `rbs_rag.llm`: API-based LLM adapters for OpenAI-compatible APIs and Gemini.
- `rbs_rag.engine`: reusable orchestration service used by CLI and future UI/API layers.
- `rbs_rag.cli`: user-facing commands.

## CLI Commands

- `rag init`: create local config and storage.
- `rag ingest PATH --kb default`: parse, chunk, embed, and index files.
- `rag search QUERY --kb default`: show retrieved chunks and metadata without calling an LLM.
- `rag ask QUERY --kb default`: retrieve evidence, call configured LLM API, and print cited answer.
- `rag chat --kb default`: interactive session with memory.
- `rag sessions list`: list saved sessions.
- `rag config show`: show effective config without secret values.
- `rag documents list`: inspect indexed documents.

## Configuration

The default config is JSON to avoid requiring YAML dependencies. It supports environment-variable references such as `${RAG_LLM_API_KEY}`. LLM provider detection is best-effort; explicit config always wins.

The LLM is API-based only. All other core RAG operations run locally.

## Tenancy And Metadata

Every document and chunk stores `tenant_id`, `knowledge_base_id`, `document_id`, `document_name`, `document_type`, `section`, `language`, `tags`, and arbitrary user-provided metadata. The local CLI defaults to `tenant_id=local` and `kb=default`, but retrieval is always tenant and KB aware.

## Validation

The first Self-RAG style validation is heuristic: it checks whether retrieval produced enough relevant context and marks answer confidence as low when grounding is weak. The engine still includes the validation boundary so later reflection or verifier models can be added without redesigning the interface.

## Testing

Tests cover config initialization, environment expansion, chunking limits, ingestion and retrieval, metadata filtering, provider detection, prompt construction, and CLI smoke behavior.

