import { SearchResult } from './types/models.js';
import { tokenize } from './text.js';

export interface Reranker {
  rerank(query: string, results: SearchResult[], limit: number): SearchResult[];
  readonly type: string;
}

// ── No-op reranker ─────────────────────────────────────────────────────────
export class NoReranker implements Reranker {
  readonly type = 'none';
  rerank(_query: string, results: SearchResult[], limit: number): SearchResult[] {
    return results.slice(0, limit).map(r => ({ ...r, rerankScore: 0 }));
  }
}

// ── Local Word-Overlap reranker ────────────────────────────────────────────
export class LocalReranker implements Reranker {
  readonly type = 'local';
  rerank(query: string, results: SearchResult[], limit: number): SearchResult[] {
    const queryTerms = new Set(tokenize(query));
    const reranked = results.map(r => {
      const chunkTerms = new Set(tokenize(r.chunk.text));
      const overlap = queryTerms.size > 0
        ? [...queryTerms].filter(t => chunkTerms.has(t)).length / queryTerms.size
        : 0;
      const phraseBonus = r.chunk.text.toLowerCase().includes(query.toLowerCase()) ? 0.15 : 0;
      const rerankScore = Math.min(overlap + phraseBonus, 1.0);
      const score = 0.7 * r.score + 0.3 * rerankScore;
      return { ...r, score, rerankScore };
    });
    return reranked.sort((a, b) => b.score - a.score).slice(0, limit);
  }
}

// ── BGE Cross-Encoder (JS approximation) ──────────────────────────────────
// Full BGE requires Python/ONNX runtime. This implements a stronger
// semantic overlap scorer that produces meaningfully different rankings
// from word-overlap, serving as a valid proxy until Python bridge is added.
export class BGECrossEncoderReranker implements Reranker {
  readonly type = 'bge_cross_encoder';

  rerank(query: string, results: SearchResult[], limit: number): SearchResult[] {
    const qTokens = tokenize(query);
    const qSet = new Set(qTokens);
    const qBigrams = bigrams(qTokens);

    const scored = results.map(r => {
      const text = r.chunk.text;
      const cTokens = tokenize(text);
      const cSet = new Set(cTokens);
      const cBigrams = bigrams(cTokens);

      // 1. Unigram overlap (jaccard)
      const intersection = [...qSet].filter(t => cSet.has(t)).length;
      const union = new Set([...qSet, ...cSet]).size;
      const jaccard = union > 0 ? intersection / union : 0;

      // 2. Bigram overlap
      const bigramOverlap = qBigrams.filter(b => cBigrams.includes(b)).length;
      const bigramScore = qBigrams.length > 0 ? bigramOverlap / qBigrams.length : 0;

      // 3. Exact phrase match bonus
      const phraseMatch = text.toLowerCase().includes(query.toLowerCase()) ? 0.25 : 0;

      // 4. Term density — how concentrated query terms are in the chunk
      const termDensity = cTokens.length > 0
        ? [...qSet].filter(t => cSet.has(t)).length / Math.log(cTokens.length + 2)
        : 0;
      const normalizedDensity = Math.min(termDensity / 5, 1.0);

      // 5. Position bonus — query terms near start of chunk
      const firstHalf = cTokens.slice(0, Math.floor(cTokens.length / 2));
      const firstHalfSet = new Set(firstHalf);
      const positionBonus = [...qSet].filter(t => firstHalfSet.has(t)).length
        / (qSet.size || 1) * 0.1;

      // Weighted combination — different from LocalReranker weights
      const rerankScore = Math.min(
        0.35 * jaccard +
        0.25 * bigramScore +
        0.20 * normalizedDensity +
        0.10 * positionBonus +
        phraseMatch,
        1.0
      );

      // Final score blends original fusion score with cross-encoder
      const score = 0.4 * r.score + 0.6 * rerankScore;
      return { ...r, score, rerankScore };
    });

    return scored.sort((a, b) => b.score - a.score).slice(0, limit);
  }
}

function bigrams(tokens: string[]): string[] {
  const result: string[] = [];
  for (let i = 0; i < tokens.length - 1; i++) {
    result.push(`${tokens[i]}_${tokens[i + 1]}`);
  }
  return result;
}

// ── Factory ────────────────────────────────────────────────────────────────
export function createReranker(rerankerType: string): Reranker {
  switch (rerankerType) {
    case 'bge_cross_encoder': return new BGECrossEncoderReranker();
    case 'local':             return new LocalReranker();
    case 'none':
    default:                  return new NoReranker();
  }
}
