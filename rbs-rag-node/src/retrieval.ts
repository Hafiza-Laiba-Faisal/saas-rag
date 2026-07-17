import { EmbeddingProvider } from './embeddings.js';
import { Chunk, SearchResult } from './types/models.js';
import { createReranker, Reranker } from './reranking.js';
import { DbStore } from './store.js';
import { QdrantVectorStore } from './vectorStore.js';
import { bm25Scores } from './text.js';

interface RetrievalProfile {
  dbFetchMs: number;
  denseEmbMs: number;
  vectorSimMs: number;
  bm25Ms: number;
  rerankMs: number;
  totalRetrievalMs: number;
  chunksScanned: number;
  qdrantHit: boolean;
}

export class HybridRetriever {
  private store: DbStore;
  private embeddingProvider: EmbeddingProvider;
  private vectorStore: QdrantVectorStore | null;
  private reranker: Reranker;
  private config: {
    topK: number;
    rerankTopK: number;
    finalContextK: number;
    denseWeight: number;
    sparseWeight: number;
  };

  constructor(
    store: DbStore,
    embeddingProvider: EmbeddingProvider,
    vectorStore: QdrantVectorStore | null,
    config: {
      topK: number;
      rerankTopK: number;
      finalContextK: number;
      denseWeight: number;
      sparseWeight: number;
      reranker: string;
    }
  ) {
    this.store = store;
    this.embeddingProvider = embeddingProvider;
    this.vectorStore = vectorStore;
    this.reranker = createReranker(config.reranker);
    this.config = config;
  }

  async search(
    query: string,
    knowledgeBaseId: string,
    tenantId: string,
    filters?: Record<string, string>
  ): Promise<{ results: SearchResult[]; profile: RetrievalProfile }> {
    const t0 = performance.now();

    const qEmbedding = (await this.embeddingProvider.embed([query]))[0];
    const tEmb = (performance.now() - t0);

    let qdrantChunks: Chunk[] = [];
    const tQd0 = performance.now();
    if (this.vectorStore?.initialized) {
      try {
        const qFilter: Record<string, string> = { knowledge_base_id: knowledgeBaseId };
        if (filters) Object.assign(qFilter, filters);
        qdrantChunks = await this.vectorStore.search('rag_chunks', qEmbedding, this.config.topK * 2, qFilter);
      } catch (err) {
        console.warn('Qdrant search failed:', (err as Error).message);
      }
    }
    const tQd = (performance.now() - tQd0);

    let allChunks: Chunk[] = [];
    let qdrantHit = false;

    if (qdrantChunks.length > 0) {
      allChunks = qdrantChunks;
      qdrantHit = true;
    } else {
      const tDb0 = performance.now();
      allChunks = await this.store.listChunks(tenantId, knowledgeBaseId);
      const _tDb = (performance.now() - tDb0);
      // not adding to profile since we track it differently
    }

    if (!allChunks.length) {
      return {
        results: [],
        profile: {
          dbFetchMs: tQd,
          denseEmbMs: tEmb,
          vectorSimMs: 0,
          bm25Ms: 0,
          rerankMs: 0,
          totalRetrievalMs: (performance.now() - t0),
          chunksScanned: 0,
          qdrantHit,
        },
      };
    }

    // Compute dense scores
    const tSim0 = performance.now();
    const denseScores: Record<string, number> = {};
    if (qdrantHit) {
      for (const chunk of allChunks) {
        denseScores[chunk.chunkId] = chunk.metadata._score || 0;
      }
    } else {
      // cosine similarity fallback
      for (const chunk of allChunks) {
        if (chunk.embedding.length) {
          denseScores[chunk.chunkId] = cosineSimilarity(qEmbedding, chunk.embedding);
        } else {
          denseScores[chunk.chunkId] = 0;
        }
      }
    }
    const tSim = (performance.now() - tSim0);

    // BM25
    const tBm25 = performance.now();
    const docTexts: Record<string, string> = {};
    for (const chunk of allChunks) docTexts[chunk.chunkId] = chunk.text;
    const sparseScores = bm25Scores(query, docTexts);
    const tBm25End = (performance.now() - tBm25);

    // Fusion
    const tRerank0 = performance.now();
    const denseRank = rankScores(denseScores);
    const sparseRank = rankScores(sparseScores);

    const results: SearchResult[] = allChunks.map(chunk => ({
      chunk,
      score: 0,
      denseScore: denseScores[chunk.chunkId] || 0,
      sparseScore: sparseScores[chunk.chunkId] || 0,
      rerankScore: 0,
    }));

    for (const r of results) {
      const d = denseRank[r.chunk.chunkId] || 0;
      const s = sparseRank[r.chunk.chunkId] || 0;
      r.score = this.config.denseWeight * d + this.config.sparseWeight * s;
    }

    const candidates = results.sort((a, b) => b.score - a.score).slice(0, this.config.topK);
    const finalResults = this.reranker.rerank(query, candidates.slice(0, this.config.rerankTopK), this.config.finalContextK);
    const tRerank = (performance.now() - tRerank0);

    return {
      results: finalResults,
      profile: {
        dbFetchMs: tQd,
        denseEmbMs: tEmb,
        vectorSimMs: tSim,
        bm25Ms: tBm25End,
        rerankMs: tRerank,
        totalRetrievalMs: (performance.now() - t0),
        chunksScanned: allChunks.length,
        qdrantHit,
      },
    };
  }
}

function rankScores(scores: Record<string, number>): Record<string, number> {
  const ordered = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const ranked: Record<string, number> = {};
  for (let i = 0; i < ordered.length; i++) {
    const [id, score] = ordered[i];
    ranked[id] = score <= 0 ? 0 : 1 / (i + 1);
  }
  return ranked;
}

function cosineSimilarity(a: number[], b: number[]): number {
  if (!a.length || !b.length || a.length !== b.length) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  na = Math.sqrt(na);
  nb = Math.sqrt(nb);
  if (na === 0 || nb === 0) return 0;
  return dot / (na * nb);
}
