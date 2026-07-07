from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .chunking import create_chunker
from .config import AppConfig, resolve_storage_path
from .document_loaders import iter_document_files, load_document
from .embeddings import create_embedding_provider, create_sparse_provider
from .llm import build_rag_messages, create_llm_client, create_streaming_client
from .models import Answer, Citation, IngestSummary, SearchResult, StreamingChunk
from .retrieval import HybridRetriever
from .store import SQLiteRagStore
from .validation import validate_retrieval, validate_streaming_answer
from .vector_store import QdrantVectorStore

log = logging.getLogger(__name__)


class RagEngine:
    def __init__(self, config: AppConfig, root: Path):
        self.config = config
        self.root = root
        self.store = SQLiteRagStore(resolve_storage_path(root, config))
        self.vector_store = QdrantVectorStore(config.qdrant)
        emb_api_key = getattr(config.embeddings, "api_key", None) or config.llm.api_key
        emb_base_url = getattr(config.embeddings, "base_url", None)
        self.embedding_provider = create_embedding_provider(
            config.embeddings.provider, config.embeddings.dimensions, config.embeddings.model,
            api_key=emb_api_key, base_url=emb_base_url,
        )
        self.sparse_provider = create_sparse_provider(
            config.embeddings.provider, config.embeddings.dimensions, config.embeddings.model,
        )
        self.chunker = create_chunker(config.chunking)
        self._start_time = time.time()
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        await self.vector_store.initialize()
        await self.vector_store.ensure_collection("rag_chunks", self.config.embeddings.dimensions)
        self._initialized = True
        log.info("RagEngine initialized (qdrant=%s, embeddings=%s, chunker=%s)",
                 self.vector_store._initialized,
                 self.config.embeddings.provider,
                 type(self.chunker).__name__)

    async def ingest_path(self, path: Path, kb: str | None = None, metadata: dict[str, str] | None = None,
                          use_ocr: bool = False, ocr_engine: str | None = None) -> IngestSummary:
        summary = IngestSummary()
        for file_path in iter_document_files(path):
            try:
                file_summary = await self.ingest_file(file_path, kb=kb, metadata=metadata, use_ocr=use_ocr, ocr_engine=ocr_engine)
                summary.documents += file_summary.documents
                summary.chunks += file_summary.chunks
                summary.skipped += file_summary.skipped
                summary.errors.extend(file_summary.errors)
            except Exception as exc:
                summary.errors.append(f"{file_path}: {exc}")
        return summary

    async def ingest_file(self, path: Path, kb: str | None = None, metadata: dict[str, str] | None = None,
                          use_ocr: bool = False, ocr_engine: str | None = None) -> IngestSummary:
        knowledge_base_id = kb or self.config.default_kb
        document = load_document(path, metadata=metadata, use_ocr=use_ocr)
        if not document.text.strip():
            return IngestSummary(skipped=1, errors=[f"{path}: no text extracted"])
        if use_ocr and document.ocr_engine is None:
            document.ocr_engine = ocr_engine or "paddle"
        chunks = self.chunker.chunk(document, tenant_id=self.config.tenant_id, knowledge_base_id=knowledge_base_id)
        embeddings = self.embedding_provider.embed([chunk.text for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding
        self.store.upsert_document(document, self.config.tenant_id, knowledge_base_id)
        self.store.upsert_chunks(chunks)

        # Also sync to Qdrant
        if self.vector_store._initialized:
            try:
                await self.vector_store.delete_document_chunks("rag_chunks", document.document_id)
                await self.vector_store.upsert_chunks("rag_chunks", chunks)
            except Exception as exc:
                log.warning("Qdrant upsert failed, SQLite fallback active: %s", exc)

        return IngestSummary(documents=1, chunks=len(chunks))

    async def delete_document(self, document_id: str):
        doc = self.store.get_document(document_id)
        if not doc:
            return
        self.store.delete_document(document_id)
        if self.vector_store._initialized:
            try:
                await self.vector_store.delete_document_chunks("rag_chunks", document_id)
            except Exception as exc:
                log.warning("Qdrant delete failed: %s", exc)

    def search(self, query: str, kb: str | None = None, filters: dict[str, str] | None = None) -> list[SearchResult]:
        retriever = self._build_retriever()
        return retriever.search(query, kb or self.config.default_kb, filters=filters)

    def search_with_profile(self, query: str, kb: str | None = None, filters: dict[str, str] | None = None) -> tuple[list[SearchResult], dict[str, float]]:
        retriever = self._build_retriever()
        return retriever.search_with_profile(query, kb or self.config.default_kb, filters=filters)

    def ask(self, query: str, kb: str | None = None, session_id: str = "default",
            user_id: str = "local-user", filters: dict[str, str] | None = None) -> Answer:
        import time
        t_start = time.perf_counter()
        retriever = self._build_retriever()
        results, ret_profile = retriever.search_with_profile(query, kb or self.config.default_kb, filters=filters)
        retrieval_ms = ret_profile.get("total_retrieval_ms", 0.0)

        validation = validate_retrieval(results)

        t_mem_start = time.perf_counter()
        user_memory_text = self.get_user_memory_text(user_id)
        session_memory_text = self.store.get_session_memory(self.config.tenant_id, session_id, user_id, limit=self.config.session_memory_limit)
        combined_memory = "\n".join(part for part in [user_memory_text, session_memory_text] if part)
        memory_ms = (time.perf_counter() - t_mem_start) * 1000.0

        messages = build_rag_messages(query, results, session_memory=combined_memory)

        t_llm_start = time.perf_counter()
        client = create_llm_client(self.config.llm)
        answer_text = client.generate(messages)
        llm_ms = (time.perf_counter() - t_llm_start) * 1000.0

        self.store.add_session_turn(self.config.tenant_id, session_id, user_id, "user", query)
        self.store.add_session_turn(self.config.tenant_id, session_id, user_id, "assistant", answer_text)

        total_ms = (time.perf_counter() - t_start) * 1000.0

        citations = [
            Citation(index=index, document_name=result.chunk.metadata.get("document_name", "unknown"),
                     section=result.chunk.metadata.get("section"), chunk_id=result.chunk.chunk_id)
            for index, result in enumerate(results, start=1)
        ]

        profile = {
            "total_ms": round(total_ms, 2),
            "retrieval_ms": round(retrieval_ms, 2),
            "memory_ms": round(memory_ms, 2),
            "llm_ms": round(llm_ms, 2),
            "llm_provider": self.config.llm.provider,
            "llm_model": self.config.llm.model,
            "subspans": {
                "retrieval": {"db_chunks_fetch_ms": ret_profile.get("db_fetch_ms", 0.0), "dense_embedding_ms": ret_profile.get("dense_emb_ms", 0.0), "vector_similarity_ms": ret_profile.get("vector_sim_ms", 0.0), "bm25_keyword_ms": ret_profile.get("bm25_ms", 0.0), "reranking_ms": ret_profile.get("rerank_ms", 0.0), "total_chunks_scanned": ret_profile.get("chunks_scanned", 0)},
                "memory": {"user_memory_ms": 0.0, "session_memory_ms": round(memory_ms, 2), "active_context_turns": self.config.session_memory_limit},
                "llm": {"prompt_build_ms": 0.0, "network_roundtrip_ms": round(llm_ms, 2), "estimated_words_generated": len(answer_text.split())},
            },
        }

        return Answer(text=answer_text, citations=citations, validation=validation, contexts=results, profile=profile)

    async def ask_stream(self, query: str, kb: str | None = None, session_id: str = "default",
                         user_id: str = "local-user", filters: dict[str, str] | None = None):
        import time
        t_start = time.perf_counter()
        retriever = self._build_retriever()
        results, ret_profile = retriever.search_with_profile(query, kb or self.config.default_kb, filters=filters)
        validation = validate_retrieval(results)
        combined_memory = "\n".join(part for part in [self.get_user_memory_text(user_id),
                                                      self.store.get_session_memory(self.config.tenant_id, session_id, user_id, limit=self.config.session_memory_limit)] if part)
        messages = build_rag_messages(query, results, session_memory=combined_memory)

        stream_client = create_streaming_client(self.config.llm)
        citations = [
            Citation(index=index, document_name=result.chunk.metadata.get("document_name", "unknown"),
                     section=result.chunk.metadata.get("section"), chunk_id=result.chunk.chunk_id)
            for index, result in enumerate(results, start=1)
        ]

        full_text = ""
        async for chunk in stream_client.generate_stream(messages):
            if chunk.error:
                yield StreamingChunk(text="", done=True, error=chunk.error, citations=citations)
                return
            full_text += chunk.text
            yield StreamingChunk(text=chunk.text, done=False)

        self.store.add_session_turn(self.config.tenant_id, session_id, user_id, "user", query)
        self.store.add_session_turn(self.config.tenant_id, session_id, user_id, "assistant", full_text)

        stream_validation = validate_streaming_answer(full_text, results)
        yield StreamingChunk(text="", done=True, citations=citations, error=None)

    def list_documents(self, kb: str | None = None) -> list[dict]:
        return self.store.list_documents(self.config.tenant_id, kb or self.config.default_kb)

    def list_sessions(self) -> list[dict]:
        return self.store.list_sessions(self.config.tenant_id)

    def get_session_turns(self, session_id: str) -> list[dict]:
        return self.store.get_session_turns(self.config.tenant_id, session_id)

    def set_user_memory(self, user_id: str, key: str, value: str) -> None:
        self.store.set_user_memory(self.config.tenant_id, user_id, key, value)

    def get_user_memory(self, user_id: str) -> dict[str, str]:
        return self.store.get_user_memory(self.config.tenant_id, user_id)

    def get_user_memory_text(self, user_id: str) -> str:
        memory = self.get_user_memory(user_id)
        return "\n".join(f"{key}: {value}" for key, value in memory.items())

    def get_health(self):
        from .models import HealthStatus
        qdrant_status = "connected" if (self.vector_store._client and self.vector_store._initialized) else "disconnected"
        llm_status = "configured" if self.config.llm.api_key else "not_configured"
        return HealthStatus(
            status="ok",
            db="connected",
            qdrant=qdrant_status,
            llm=llm_status,
            embeddings=self.config.embeddings.provider,
            uptime_seconds=round(time.time() - self._start_time, 2),
            total_documents=self.store.count_documents(self.config.tenant_id, self.config.default_kb),
            total_chunks=self.store.count_chunks(self.config.tenant_id, self.config.default_kb),
        )

    def get_profile_llm(self):
        return {"provider": self.config.llm.provider, "model": self.config.llm.model}

    async def close(self):
        if self.vector_store:
            await self.vector_store.close()

    def _build_retriever(self):
        return HybridRetriever(
            store=self.store,
            embedding_provider=self.embedding_provider,
            tenant_id=self.config.tenant_id,
            top_k=self.config.retrieval.top_k,
            rerank_top_k=self.config.retrieval.rerank_top_k,
            final_context_k=self.config.retrieval.final_context_k,
            dense_weight=self.config.retrieval.dense_weight,
            sparse_weight=self.config.retrieval.sparse_weight,
            vector_store=self.vector_store if self.vector_store._initialized else None,
        )
