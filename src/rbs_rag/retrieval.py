from __future__ import annotations

import logging
from dataclasses import dataclass

from .embeddings import EmbeddingProvider
from .models import Chunk, SearchResult
from .reranking import create_reranker
from .store import SQLiteRagStore
from .text import bm25_scores, cosine_similarity
from .vector_store import QdrantVectorStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class HybridRetriever:
    store: SQLiteRagStore
    embedding_provider: EmbeddingProvider
    tenant_id: str
    top_k: int = 20
    rerank_top_k: int = 8
    final_context_k: int = 5
    dense_weight: float = 0.55
    sparse_weight: float = 0.45
    vector_store: QdrantVectorStore | None = None
    collection: str = "rag_chunks"

    def search(self, query: str, knowledge_base_id: str, filters: dict[str, str] | None = None) -> list[SearchResult]:
        results, _ = self.search_with_profile(query, knowledge_base_id, filters)
        return results

    def search_with_profile(self, query: str, knowledge_base_id: str, filters: dict[str, str] | None = None) -> tuple[list[SearchResult], dict[str, float]]:
        import time
        t0 = time.perf_counter()

        query_embedding = self.embedding_provider.embed([query])[0]
        t_emb_ms = (time.perf_counter() - t0) * 1000.0

        qdrant_results: list[tuple[Chunk, float]] = []

        # Phase 1: Qdrant vector search
        t_qd0 = time.perf_counter()
        if self.vector_store:
            try:
                kb_filter = {"knowledge_base_id": knowledge_base_id}
                if filters:
                    kb_filter.update(filters)
                qdrant_chunks = self.vector_store.search(
                    self.collection,
                    query_embedding,
                    top_k=self.top_k * 2,
                    filters=kb_filter,
                )
                qdrant_results = [(c, c.metadata.get("_score", 0.0)) for c in qdrant_chunks]
            except Exception as exc:
                log.warning("Qdrant search failed, falling back to SQLite: %s", exc)
        t_qd_ms = (time.perf_counter() - t_qd0) * 1000.0

        # Phase 2: fallback SQLite brute-force if Qdrant returned nothing
        t_db0 = time.perf_counter()
        sqlite_chunks = self.store.list_chunks(self.tenant_id, knowledge_base_id, filters) if not qdrant_results else []
        t_db_ms = (time.perf_counter() - t_db0) * 1000.0

        all_chunks: list[Chunk] = []
        if qdrant_results:
            all_chunks = [c for c, _ in qdrant_results]
        elif sqlite_chunks:
            all_chunks = sqlite_chunks
        else:
            return [], {"db_fetch_ms": round(t_db_ms + t_qd_ms, 2), "dense_emb_ms": 0.0, "vector_sim_ms": 0.0, "bm25_ms": 0.0, "rerank_ms": 0.0, "total_retrieval_ms": round((time.perf_counter() - t0) * 1000.0, 2), "chunks_scanned": 0}

        # Phase 3: Compute scores (only needed for SQLite fallback or hybrid fusion)
        t_sim0 = time.perf_counter()
        dense_scores = {}
        if not qdrant_results:
            for chunk in all_chunks:
                dense_scores[chunk.chunk_id] = cosine_similarity(query_embedding, chunk.embedding)
        else:
            for chunk, score in qdrant_results:
                dense_scores[chunk.chunk_id] = score
        t_sim_ms = (time.perf_counter() - t_sim0) * 1000.0

        # Phase 4: Sparse BM25
        t_bm25_0 = time.perf_counter()
        sparse_scores = bm25_scores(query, {chunk.chunk_id: chunk.text for chunk in all_chunks})
        t_bm25_ms = (time.perf_counter() - t_bm25_0) * 1000.0

        # Phase 5: Fusion
        t_rerank0 = time.perf_counter()
        dense_rank = _rank_scores(dense_scores)
        sparse_rank = _rank_scores(sparse_scores)

        results = []
        for chunk in all_chunks:
            dense = dense_scores.get(chunk.chunk_id, 0.0)
            sparse = sparse_scores.get(chunk.chunk_id, 0.0)
            fused = self.dense_weight * dense_rank.get(chunk.chunk_id, 0.0) + self.sparse_weight * sparse_rank.get(chunk.chunk_id, 0.0)
            results.append(SearchResult(chunk=chunk, score=fused, dense_score=dense, sparse_score=sparse))

        candidates = sorted(results, key=lambda item: item.score, reverse=True)[:self.top_k]

        reranker = create_reranker("local")
        final_results = reranker.rerank(query, candidates[:self.rerank_top_k], self.final_context_k)
        t_rerank_ms = (time.perf_counter() - t_rerank0) * 1000.0

        total_retrieval_ms = (time.perf_counter() - t0) * 1000.0

        profile = {
            "db_fetch_ms": round(t_db_ms + t_qd_ms, 2),
            "dense_emb_ms": round(t_emb_ms, 2),
            "vector_sim_ms": round(t_sim_ms, 2),
            "bm25_ms": round(t_bm25_ms, 2),
            "rerank_ms": round(t_rerank_ms, 2),
            "total_retrieval_ms": round(total_retrieval_ms, 2),
            "chunks_scanned": len(all_chunks),
            "qdrant_hit": bool(qdrant_results),
        }

        return final_results, profile


def _rank_scores(scores: dict[str, float]) -> dict[str, float]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ranked: dict[str, float] = {}
    for rank, (chunk_id, score) in enumerate(ordered, start=1):
        if score <= 0:
            ranked[chunk_id] = 0.0
        else:
            ranked[chunk_id] = 1.0 / rank
    return ranked
