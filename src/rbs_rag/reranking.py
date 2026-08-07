from __future__ import annotations

import logging
from dataclasses import replace
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


def create_reranker(reranker_type: str) -> Reranker:
    return LocalReranker()
