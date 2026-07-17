import { QdrantClient } from '@qdrant/js-client-rest';
import { v5 as uuidv5 } from 'uuid';
import { Chunk } from './types/models.js';

const NAMESPACE_DNS = '6ba7b810-9dad-11d1-80b4-00c04fd430c8';
const KNOWN_PAYLOAD_FIELDS = new Set(['chunk_id', 'document_id', 'text', 'ordinal']);

export class QdrantVectorStore {
  private client: QdrantClient | null = null;
  private config: { host: string; port: number; apiKey: string; https: boolean };
  initialized = false;

  constructor(config: { host: string; port: number; apiKey: string; https: boolean }) {
    this.config = config;
  }

  async initialize(): Promise<void> {
    try {
      const url = `${this.config.https ? 'https' : 'http'}://${this.config.host}:${this.config.port}`;
      this.client = new QdrantClient({ url, apiKey: this.config.apiKey || undefined, checkCompatibility: false });
      this.initialized = true;
    } catch (err) {
      console.warn('Qdrant client init error:', (err as Error).message);
    }
  }

  async ensureCollection(collection: string, vectorSize = 384): Promise<void> {
    if (!this.client || !this.initialized) return;
    try {
      await this.client.getCollection(collection);
    } catch {
      try {
        await this.client!.createCollection(collection, {
          vectors: { size: vectorSize, distance: 'Cosine' },
          optimizers_config: { default_segment_number: 2 },
          replication_factor: 1,
        } as any);
      } catch {
        console.warn(`Qdrant: cannot create collection ${collection}`);
      }
    }
  }

  async search(
    collection: string,
    queryVector: number[],
    topK = 20,
    filters?: Record<string, string>
  ): Promise<Chunk[]> {
    if (!this.client || !this.initialized) return [];
    try {
      const queryFilter = buildFilter(filters);
      const result = await this.client.query(collection, {
        query: queryVector,
        limit: topK,
        with_payload: true,
        filter: queryFilter || undefined,
      } as any);
      return (result.points || []).map(p => pointToChunk(p));
    } catch {
      return [];
    }
  }

  async scrollAllChunks(collection: string, limit = 100): Promise<Chunk[]> {
    if (!this.client || !this.initialized) return [];
    try {
      const result = await this.client.scroll(collection, { limit, with_payload: true } as any);
      return result.points.map(p => pointToChunk(p));
    } catch {
      return [];
    }
  }

  async countChunks(collection: string): Promise<number> {
    if (!this.client || !this.initialized) return 0;
    try {
      const result = await this.client.count(collection);
      return result.count;
    } catch {
      return 0;
    }
  }

  async deleteCollection(collection: string): Promise<void> {
    if (!this.client || !this.initialized) return;
    try { await this.client.deleteCollection(collection); } catch {}
  }

  async deleteDocumentChunks(collection: string, documentId: string): Promise<void> {
    if (!this.client || !this.initialized) return;
    try {
      await this.client.delete(collection, {
        filter: { must: [{ key: 'document_id', match: { value: documentId } }] },
        wait: true,
      });
    } catch {}
  }

  async upsertChunks(collection: string, chunks: Chunk[], batchSize = 64): Promise<void> {
    if (!this.client || !this.initialized) return;
    try {
      const points = chunks.map(chunk => {
        const payload: Record<string, any> = {
          chunk_id: chunk.chunkId,
          document_id: chunk.documentId,
          text: chunk.text,
          ordinal: chunk.ordinal,
        };
        for (const [k, v] of Object.entries(chunk.metadata)) {
          payload[k] = v;
        }
        return {
          id: makePointId(chunk.chunkId),
          vector: chunk.embedding,
          payload,
        };
      });
      for (let i = 0; i < points.length; i += batchSize) {
        await this.client.upsert(collection, { points: points.slice(i, i + batchSize), wait: true });
      }
    } catch {}
  }
}

function makePointId(chunkId: string): string {
  return uuidv5(chunkId, NAMESPACE_DNS);
}

function buildFilter(filters?: Record<string, string>): any {
  if (!filters || !Object.keys(filters).length) return undefined;
  return { must: Object.entries(filters).map(([key, value]) => ({ key, match: { value } })) };
}

function pointToChunk(point: any): Chunk {
  const payload = point.payload || {};
  const metadata: Record<string, any> = {};
  for (const [k, v] of Object.entries(payload)) {
    if (!KNOWN_PAYLOAD_FIELDS.has(k)) metadata[k] = v;
  }
  metadata['_score'] = point.score || 0;
  const vector = Array.isArray(point.vector) ? point.vector : (point.vector || []);
  return {
    chunkId: payload.chunk_id || String(point.id),
    documentId: payload.document_id || '',
    text: payload.text || '',
    ordinal: payload.ordinal || 0,
    metadata,
    embedding: vector,
  };
}
