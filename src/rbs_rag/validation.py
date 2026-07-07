from __future__ import annotations

import math

from .models import RetrievalValidation, SearchResult


def validate_retrieval(results: list[SearchResult]) -> RetrievalValidation:
    if not results:
        return RetrievalValidation(False, "none", ["No context was retrieved."], citation_quality=0.0, answer_completeness=0.0, confidence_score=0.0)

    best_score = results[0].score
    avg_score = sum(r.score for r in results) / len(results)
    score_variance = sum((r.score - avg_score) ** 2 for r in results) / len(results) if len(results) > 1 else 0.0

    scores = [r.score for r in results]
    total_context_len = sum(len(r.chunk.text.split()) for r in results)

    # Citation quality: how well scores are distributed and absolute level
    citation_quality = min(avg_score * (1.0 + 0.2 * math.log(len(results) + 1)), 1.0)

    # Answer completeness: high score spread suggests diverse coverage
    completeness = min(avg_score * (1.0 + 0.15 * math.log(total_context_len + 1)), 1.0)

    # Confidence calibration based on multiple signals
    confidence_base = best_score * 0.5 + avg_score * 0.3
    variance_penalty = min(score_variance * 2.0, 0.2)
    coverage_bonus = min(len(results) * 0.05, 0.15)
    confidence_score = max(min(confidence_base - variance_penalty + coverage_bonus, 1.0), 0.0)

    if best_score < 0.08:
        reasons = ["Retrieved context has weak similarity to the question."]
        return RetrievalValidation(False, "low", reasons, citation_quality, completeness, confidence_score)

    if len(results) == 1:
        reasons = ["Only one supporting context chunk was retrieved."]
        return RetrievalValidation(True, "medium", reasons, citation_quality, completeness, confidence_score)

    if best_score >= 0.25:
        reasons = ["Retrieved context has strong relevance signals."]
        return RetrievalValidation(True, "high", reasons, citation_quality, completeness, confidence_score)

    if confidence_score >= 0.5:
        reasons = ["Retrieved context appears relevant based on combined confidence signals."]
        return RetrievalValidation(True, "medium", reasons, citation_quality, completeness, confidence_score)

    reasons = ["Retrieved context should be cited carefully; confidence is moderate."]
    return RetrievalValidation(True, "medium", reasons, citation_quality, completeness, confidence_score)


def validate_streaming_answer(answer_text: str, results: list[SearchResult]) -> RetrievalValidation:
    if not answer_text.strip():
        return RetrievalValidation(False, "none", ["Empty answer generated."])

    cited_indices = set()
    import re
    for match in re.finditer(r"\[(\d+)\]", answer_text):
        cited_indices.add(int(match.group(1)))

    if not cited_indices:
        return RetrievalValidation(True, "low", ["Answer does not contain citations."])

    valid_citations = sum(1 for i in cited_indices if 1 <= i <= len(results))
    if valid_citations == 0:
        return RetrievalValidation(True, "low", ["Citations in answer do not match retrieved context indices."])

    citation_quality = valid_citations / max(len(cited_indices), 1)
    reasons = [f"Answer cites {valid_citations}/{len(cited_indices)} sources."]
    if citation_quality >= 0.8:
        return RetrievalValidation(True, "high", reasons)
    return RetrievalValidation(True, "medium", reasons)
