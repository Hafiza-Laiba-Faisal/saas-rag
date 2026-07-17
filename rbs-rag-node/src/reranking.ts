import { SearchResult } from './types/models.js';
import { tokenize } from './text.js';

export interface Reranker {
  rerank(query: string, results: SearchResult[], limit: number): SearchResult[];
}

export class LocalReranker implements Reranker {
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

export function createReranker(rerankerType: string): Reranker {
  return new LocalReranker();
}
