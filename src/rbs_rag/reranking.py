from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol

from .models import SearchResult
from .text import tokenize

log = logging.getLogger(__name__)


class Reranker(Protocol):
    def rerank(self, query: str, results: list[SearchResult], limit: int) -> list[SearchResult]:
        ...


class LocalReranker:
    def rerank(self, query: str, results: list[SearchResult], limit: int) -> list[SearchResult]:
        query_terms = set(tokenize(query))
        reranked: list[SearchResult] = []
        for result in results:
            chunk_terms = set(tokenize(result.chunk.text))
            overlap = len(query_terms & chunk_terms) / max(len(query_terms), 1)
            phrase_bonus = 0.15 if query.lower() in result.chunk.text.lower() else 0.0
            rerank_score = min(overlap + phrase_bonus, 1.0)
            score = (0.7 * result.score) + (0.3 * rerank_score)
            reranked.append(replace(result, score=score, rerank_score=rerank_score))
        return sorted(reranked, key=lambda item: item.score, reverse=True)[:limit]


@dataclass
class BGECrossEncoderReranker:
    model: str = "BAAI/bge-reranker-v2-m3"
    _encoder: object | None = None

    def _lazy_init(self):
        if self._encoder is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
            self._encoder = CrossEncoder(self.model)
            log.info("Loaded BGE reranker: %s", self.model)
        except ImportError as exc:
            log.warning("sentence_transformers not installed, falling back to LocalReranker: %s", exc)
            self._encoder = False

    def rerank(self, query: str, results: list[SearchResult], limit: int) -> list[SearchResult]:
        self._lazy_init()
        if not self._encoder:
            return LocalReranker().rerank(query, results, limit)
        pairs = [[query, r.chunk.text] for r in results]
        try:
            scores = self._encoder.predict(pairs)
        except Exception as exc:
            log.warning("BGE reranker failed (%s), falling back to LocalReranker", exc)
            return LocalReranker().rerank(query, results, limit)
        reranked = []
        for result, score in zip(results, scores):
            reranked.append(replace(result, score=float(score), rerank_score=float(score)))
        return sorted(reranked, key=lambda item: item.score, reverse=True)[:limit]


def create_reranker(reranker_type: str) -> Reranker:
    if reranker_type in ("bge_cross_encoder", "bge-reranker"):
        return BGECrossEncoderReranker()
    return LocalReranker()
