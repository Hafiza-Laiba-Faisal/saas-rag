import { RetrievalValidation, SearchResult } from './types/models.js';

export function validateRetrieval(results: SearchResult[]): RetrievalValidation {
  if (!results.length) {
    return {
      sufficient: false,
      confidence: 'none',
      reasons: ['No context was retrieved.'],
      citationQuality: 0,
      answerCompleteness: 0,
      confidenceScore: 0,
    };
  }

  const bestScore = results[0].score;
  const avgScore = results.reduce((s, r) => s + r.score, 0) / results.length;
  const scoreVariance = results.length > 1
    ? results.reduce((s, r) => s + (r.score - avgScore) ** 2, 0) / results.length
    : 0;
  const totalContextLen = results.reduce((s, r) => s + r.chunk.text.split(/\s+/).length, 0);

  const citationQuality = Math.min(avgScore * (1 + 0.2 * Math.log(results.length + 1)), 1);
  const completeness = Math.min(avgScore * (1 + 0.15 * Math.log(totalContextLen + 1)), 1);
  const confidenceBase = bestScore * 0.5 + avgScore * 0.3;
  const variancePenalty = Math.min(scoreVariance * 2, 0.2);
  const coverageBonus = Math.min(results.length * 0.05, 0.15);
  const confidenceScore = Math.max(Math.min(confidenceBase - variancePenalty + coverageBonus, 1), 0);

  if (bestScore < 0.08) {
    return {
      sufficient: false,
      confidence: 'low',
      reasons: ['Retrieved context has weak similarity to the question.'],
      citationQuality,
      answerCompleteness: completeness,
      confidenceScore,
    };
  }

  if (results.length === 1) {
    return {
      sufficient: true,
      confidence: 'medium',
      reasons: ['Only one supporting context chunk was retrieved.'],
      citationQuality,
      answerCompleteness: completeness,
      confidenceScore,
    };
  }

  if (bestScore >= 0.25) {
    return {
      sufficient: true,
      confidence: 'high',
      reasons: ['Retrieved context has strong relevance signals.'],
      citationQuality,
      answerCompleteness: completeness,
      confidenceScore,
    };
  }

  if (confidenceScore >= 0.5) {
    return {
      sufficient: true,
      confidence: 'medium',
      reasons: ['Retrieved context appears relevant based on combined confidence signals.'],
      citationQuality,
      answerCompleteness: completeness,
      confidenceScore,
    };
  }

  return {
    sufficient: true,
    confidence: 'medium',
    reasons: ['Retrieved context should be cited carefully; confidence is moderate.'],
    citationQuality,
    answerCompleteness: completeness,
    confidenceScore,
  };
}

export function validateStreamingAnswer(answerText: string, results: SearchResult[]): RetrievalValidation {
  if (!answerText.trim()) {
    return {
      sufficient: false,
      confidence: 'none',
      reasons: ['Empty answer generated.'],
      citationQuality: 0,
      answerCompleteness: 0,
      confidenceScore: 0,
    };
  }

  const citedIndices = new Set<number>();
  const re = /\[(\d+)\]/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(answerText)) !== null) {
    citedIndices.add(parseInt(match[1], 10));
  }

  if (!citedIndices.size) {
    return {
      sufficient: true,
      confidence: 'low',
      reasons: ['Answer does not contain citations.'],
      citationQuality: 0,
      answerCompleteness: 1,
      confidenceScore: 0.3,
    };
  }

  const validCitations = [...citedIndices].filter(i => i >= 1 && i <= results.length).length;
  const citationQuality = validCitations / Math.max(citedIndices.size, 1);
  const reasons = [`Answer cites ${validCitations}/${citedIndices.size} sources.`];
  const confidence = citationQuality >= 0.8 ? 'high' : 'medium';

  return {
    sufficient: true,
    confidence,
    reasons,
    citationQuality,
    answerCompleteness: 1,
    confidenceScore: citationQuality,
  };
}
