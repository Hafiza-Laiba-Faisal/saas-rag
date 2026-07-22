import { EmbeddingProvider } from './embeddings.js';
import { Chunk, SearchResult } from './types/models.js';
import { createReranker, Reranker } from './reranking.js';
import { DbStore } from './store.js';
import { QdrantVectorStore } from './vectorStore.js';
import { bm25Scores, normalizeQuery } from './text.js';

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

    // Query Normalization
    const normalizedQuery = normalizeQuery(query);

    const qEmbedding = (await this.embeddingProvider.embed([normalizedQuery]))[0];
    const tEmb = (performance.now() - t0);

    // 1. Fetch ALL chunks from SQLite for this tenant & KB to act as the full candidate pool
    const tDb0 = performance.now();
    const allChunks = await this.store.listChunks(tenantId, knowledgeBaseId, filters);
    const tDb = (performance.now() - tDb0);

    // 2. Query Qdrant for top dense hits
    let qdrantChunks: Chunk[] = [];
    const tQd0 = performance.now();
    let qdrantHit = false;
    if (this.vectorStore?.initialized) {
      try {
        const qFilter: Record<string, string> = { knowledge_base_id: knowledgeBaseId };
        if (filters) Object.assign(qFilter, filters);
        qdrantChunks = await this.vectorStore.search('rag_chunks', qEmbedding, this.config.topK * 2, qFilter);
        qdrantHit = qdrantChunks.length > 0;
      } catch (err) {
        console.warn('Qdrant search failed:', (err as Error).message);
      }
    }
    const tQd = (performance.now() - tQd0);

    // 3. Exclude non-searchable document types (images, CSS, JS, HTML boilerplate, empty output)
    const EXCLUDED_DOC_TYPES = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'css', 'js', 'html']);
    
    const filteredChunks = allChunks.filter(chunk => {
      if (!chunk.text || !chunk.text.trim()) return false;
      const docType = (chunk.metadata?.document_type || '').toLowerCase();
      const docName = (chunk.metadata?.document_name || '').toLowerCase();
      const docExt = docName.split('.').pop() || '';
      return !EXCLUDED_DOC_TYPES.has(docType) && !EXCLUDED_DOC_TYPES.has(docExt);
    });

    const filteredQdrantChunks = qdrantChunks.filter(chunk => {
      if (!chunk.text || !chunk.text.trim()) return false;
      const docType = (chunk.metadata?.document_type || '').toLowerCase();
      const docName = (chunk.metadata?.document_name || '').toLowerCase();
      const docExt = docName.split('.').pop() || '';
      return !EXCLUDED_DOC_TYPES.has(docType) && !EXCLUDED_DOC_TYPES.has(docExt);
    });

    if (!filteredChunks.length) {
      return {
        results: [],
        profile: {
          dbFetchMs: tDb,
          denseEmbMs: tEmb,
          vectorSimMs: tQd,
          bm25Ms: 0,
          rerankMs: 0,
          totalRetrievalMs: (performance.now() - t0),
          chunksScanned: 0,
          qdrantHit,
        },
      };
    }

    // 4. Compute dense scores
    const tSim0 = performance.now();
    const denseScores: Record<string, number> = {};
    for (const chunk of filteredChunks) {
      denseScores[chunk.chunkId] = 0;
    }

    if (qdrantHit) {
      for (const chunk of filteredQdrantChunks) {
        denseScores[chunk.chunkId] = chunk.metadata._score || 0;
      }
    } else {
      // cosine similarity fallback
      for (const chunk of filteredChunks) {
        if (chunk.embedding.length) {
          denseScores[chunk.chunkId] = cosineSimilarity(qEmbedding, chunk.embedding);
        }
      }
    }
    const tSim = (performance.now() - tSim0);

    // 5. BM25 on the full set of filtered candidates
    // TODO: Replace in-memory BM25 scan with an inverted-index based implementation for large corpora.
    const tBm25 = performance.now();
    const docTexts: Record<string, string> = {};
    for (const chunk of filteredChunks) docTexts[chunk.chunkId] = chunk.text;
    const sparseScores = bm25Scores(normalizedQuery, docTexts);
    const tBm25End = (performance.now() - tBm25);

    // 6. Reciprocal Rank Fusion (RRF k=60)
    const tRerank0 = performance.now();
    const denseRank = rankScores(denseScores, 60);
    const sparseRank = rankScores(sparseScores, 60);

    const results: SearchResult[] = filteredChunks.map(chunk => ({
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

    // Slicing top candidates (topK = 20) before feeding to reranker (Top 20 candidates only)
    const candidates = results.sort((a, b) => b.score - a.score).slice(0, this.config.topK);
    const finalResults = this.reranker.rerank(normalizedQuery, candidates.slice(0, this.config.rerankTopK), this.config.finalContextK);
    const tRerank = (performance.now() - tRerank0);

    return {
      results: finalResults,
      profile: {
        dbFetchMs: tDb,
        denseEmbMs: tEmb,
        vectorSimMs: qdrantHit ? tQd : tSim,
        bm25Ms: tBm25End,
        rerankMs: tRerank,
        totalRetrievalMs: (performance.now() - t0),
        chunksScanned: filteredChunks.length,
        qdrantHit,
      },
    };
  }
}

function rankScores(scores: Record<string, number>, k = 60): Record<string, number> {
  const ordered = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const ranked: Record<string, number> = {};
  for (let i = 0; i < ordered.length; i++) {
    const [id, score] = ordered[i];
    ranked[id] = score <= 0 ? 0 : 1 / (k + i + 1);
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
