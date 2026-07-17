import { v4 as uuidv4 } from 'uuid';
import { AppConfig, tenantConfigFromRow } from './config.js';
import { DbStore } from './store.js';
import { AdminStore } from './adminStore.js';
import { QdrantVectorStore } from './vectorStore.js';
import { createEmbeddingProvider, EmbeddingProvider } from './embeddings.js';
import { HierarchicalChunker, createChunker } from './chunking.js';
import { LLMClient, buildRagMessages } from './llm.js';
import { HybridRetriever } from './retrieval.js';
import { validateRetrieval, validateStreamingAnswer } from './validation.js';
import { loadDocument, documentId, iterDocumentFiles } from './documentLoaders.js';
import {
  Answer, Citation, Chunk, IngestSummary, LoadedDocument,
  SearchResult, StreamingChunk,
} from './types/models.js';

export class RagEngine {
  config: AppConfig;
  store: DbStore;
  adminStore: AdminStore;
  vectorStore: QdrantVectorStore;
  embeddingProvider: EmbeddingProvider;
  chunker: HierarchicalChunker;
  llmClient: LLMClient;
  retriever: HybridRetriever;
  initialized = false;

  constructor(config: AppConfig, store: DbStore, adminStore: AdminStore) {
    this.config = config;
    this.store = store;
    this.adminStore = adminStore;
    this.vectorStore = new QdrantVectorStore(config.qdrant);
    this.embeddingProvider = createEmbeddingProvider(config.embeddings);
    this.chunker = createChunker(config.chunking);
    this.llmClient = new LLMClient(config.llm);
    this.retriever = new HybridRetriever(store, this.embeddingProvider, this.vectorStore, config.retrieval);
  }

  async initialize(): Promise<void> {
    if (this.initialized) return;
    try {
      await this.vectorStore.initialize();
      await this.vectorStore.ensureCollection('rag_chunks', this.config.embeddings.dimensions);
    } catch {
      // Qdrant not available — continue in degraded mode
    }
    this.initialized = true;
  }

  async ingest(
    tenantId: string,
    knowledgeBaseId: string,
    applyOcr = false
  ): Promise<IngestSummary> {
    const tenantDir = `${this.config.rootDir}/tenants/${tenantId}/documents`;
    const files = iterDocumentFiles(tenantDir);

    const summary: IngestSummary = { documents: 0, chunks: 0, skipped: 0, errors: [] };

    // Get already-ingested IDs
    const existingDocs = await this.store.listDocuments(tenantId, knowledgeBaseId);
    const existingIds = new Set(existingDocs.map((d: any) => d.documentId));

    for (const filePath of files) {
      const docId = documentId(filePath);
      if (existingIds.has(docId)) {
        summary.skipped++;
        continue;
      }

      try {
        const document = await loadDocument(filePath, undefined, applyOcr, this.config.ocr.serviceUrl, this.config.ocr.apiKey);
        if (!document.text.trim()) {
          summary.errors.push(`${document.name}: no text extracted`);
          continue;
        }

        const chunks = this.chunker.chunk(document, tenantId, knowledgeBaseId);
        const embeddings = await this.embeddingProvider.embed(chunks.map(c => c.text));
        for (let i = 0; i < chunks.length; i++) {
          chunks[i].embedding = embeddings[i];
        }

        const source = document.name.toLowerCase().includes('scraped') ? 'scrape' : 'upload';
        await this.store.upsertDocument(document, tenantId, knowledgeBaseId, source);
        await this.store.upsertChunks(chunks);
        await this.vectorStore.upsertChunks('rag_chunks', chunks);

        summary.documents++;
        summary.chunks += chunks.length;
      } catch (err: any) {
        summary.errors.push(`${filePath}: ${err.message}`);
      }
    }

    return summary;
  }

  async deleteDocument(documentId: string): Promise<void> {
    await this.vectorStore.deleteDocumentChunks('rag_chunks', documentId);
    await this.store.deleteDocument(documentId);
  }

  async ask(
    query: string,
    knowledgeBaseId: string,
    sessionId = 'default',
    userId = 'local-user',
    filters?: Record<string, string> | null,
    systemPrompt?: string | null
  ): Promise<Answer> {
    const t0 = performance.now();

    const { results, profile: retProfile } = await this.retriever.search(
      query, knowledgeBaseId, this.config.tenantId, filters || undefined
    );

    const validation = validateRetrieval(results);

    const combinedMemory = await this.store.getSessionMemory(
      this.config.tenantId, sessionId, userId, this.config.sessionMemoryLimit
    );

    const messages = buildRagMessages(query, results, combinedMemory, systemPrompt || undefined);
    const tLlm0 = performance.now();
    const answerText = await this.llmClient.generate(messages);
    const llmMs = performance.now() - tLlm0;

    const citations: Citation[] = results.map((r, i) => ({
      index: i + 1,
      documentName: r.chunk.metadata.document_name || 'unknown',
      section: r.chunk.metadata.section || null,
      chunkId: r.chunk.chunkId,
    }));

    await this.store.addSessionTurn(this.config.tenantId, sessionId, userId, 'user', query);
    await this.store.addSessionTurn(this.config.tenantId, sessionId, userId, 'assistant', answerText);

    const totalMs = performance.now() - t0;

    return {
      text: answerText,
      citations,
      validation,
      contexts: results,
      profile: {
        totalMs: Math.round(totalMs * 100) / 100,
        retrievalMs: Math.round(retProfile.totalRetrievalMs * 100) / 100,
        llmMs: Math.round(llmMs * 100) / 100,
        ...retProfile,
      },
      streaming: false,
    };
  }

  async *askStream(
    query: string,
    knowledgeBaseId: string,
    sessionId = 'default',
    userId = 'local-user',
    filters?: Record<string, string> | null,
    systemPrompt?: string | null
  ): AsyncGenerator<StreamingChunk> {
    const { results, profile: retProfile } = await this.retriever.search(
      query, knowledgeBaseId, this.config.tenantId, filters || undefined
    );

    const combinedMemory = await this.store.getSessionMemory(
      this.config.tenantId, sessionId, userId, this.config.sessionMemoryLimit
    );

    const messages = buildRagMessages(query, results, combinedMemory, systemPrompt || undefined);

    const citations: Citation[] = results.map((r, i) => ({
      index: i + 1,
      documentName: r.chunk.metadata.document_name || 'unknown',
      section: r.chunk.metadata.section || null,
      chunkId: r.chunk.chunkId,
    }));

    let fullText = '';
    const stream = await this.llmClient.generateStream(messages);
    for await (const chunk of stream) {
      if (chunk.error) {
        yield { text: '', done: true, error: chunk.error, citations };
        return;
      }
      fullText += chunk.text;
      yield { text: chunk.text, done: false };
    }

    await this.store.addSessionTurn(this.config.tenantId, sessionId, userId, 'user', query);
    await this.store.addSessionTurn(this.config.tenantId, sessionId, userId, 'assistant', fullText);

    yield { text: '', done: true, citations };
  }
}

export async function createEngineFromTenant(
  tenant: any,
  rootDir: string,
  store: DbStore,
  adminStore: AdminStore
): Promise<RagEngine> {
  const config = tenantConfigFromRow(tenant, rootDir);
  const engine = new RagEngine(config, store, adminStore);
  await engine.initialize();
  return engine;
}
