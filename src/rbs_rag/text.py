from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'-]*")


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def l2_normalize(values: Iterable[float]) -> list[float]:
    vector = list(values)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def bm25_scores(query: str, documents: dict[str, str], k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
    query_terms = tokenize(query)
    if not query_terms or not documents:
        return {doc_id: 0.0 for doc_id in documents}

    tokenized = {doc_id: tokenize(text) for doc_id, text in documents.items()}
    lengths = {doc_id: len(tokens) for doc_id, tokens in tokenized.items()}
    avg_length = sum(lengths.values()) / max(len(lengths), 1)
    doc_freq: Counter[str] = Counter()
    for tokens in tokenized.values():
        doc_freq.update(set(tokens))

    total_docs = len(documents)
    scores: dict[str, float] = {}
    for doc_id, tokens in tokenized.items():
        frequencies = Counter(tokens)
        score = 0.0
        doc_length = max(lengths[doc_id], 1)
        for term in query_terms:
            if frequencies[term] == 0:
                continue
            idf = math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            numerator = frequencies[term] * (k1 + 1)
            denominator = frequencies[term] + k1 * (1 - b + b * doc_length / max(avg_length, 1))
            score += idf * numerator / denominator
        scores[doc_id] = score
    return scores

