import dotenv from 'dotenv';
import path from 'path';

dotenv.config();

export interface LLMConfig {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string | null;
  fallbackModels: string[];
}

export interface EmbeddingConfig {
  provider: string;
  dimensions: number;
  model: string;
  baseUrl: string | null;
  apiKey: string | null;
}

export interface RetrievalConfig {
  topK: number;
  rerankTopK: number;
  finalContextK: number;
  denseWeight: number;
  sparseWeight: number;
  reranker: string;
}

export interface ChunkingConfig {
  maxTokens: number;
  overlapTokens: number;
  semanticChunking: boolean;
  semanticSimilarityThreshold: number;
}

export interface QdrantConfig {
  host: string;
  port: number;
  apiKey: string;
  https: boolean;
}

export interface RateLimitConfig {
  enabled: boolean;
  requestsPerMinute: number;
}

export interface SecurityConfig {
  adminJwtSecret: string;
  adminPassword: string;
  corsOrigins: string[];
}

export interface AppConfig {
  port: number;
  logLevel: string;
  tenantId: string;
  defaultKb: string;
  sessionMemoryLimit: number;
  chatRetentionDays: number;
  rootDir: string;
  llm: LLMConfig;
  embeddings: EmbeddingConfig;
  retrieval: RetrievalConfig;
  chunking: ChunkingConfig;
  qdrant: QdrantConfig;
  rateLimit: RateLimitConfig;
  security: SecurityConfig;
}

export function loadConfig(): AppConfig {
  return {
    port: parseInt(process.env.PORT || '3001', 10),
    logLevel: process.env.LOG_LEVEL || 'info',
    tenantId: process.env.TENANT_ID || 'local',
    defaultKb: 'default',
    sessionMemoryLimit: parseInt(process.env.SESSION_MEMORY_LIMIT || '8', 10),
    chatRetentionDays: parseInt(process.env.CHAT_RETENTION_DAYS || '30', 10),
    rootDir: process.env.RAG_ROOT_DIR || path.resolve(process.cwd(), '.rbs_rag'),
    llm: {
      provider: process.env.LLM_PROVIDER || 'gemini',
      apiKey: process.env.LLM_API_KEY || '',
      model: process.env.LLM_MODEL || 'gemini-2.5-flash-lite',
      baseUrl: process.env.LLM_BASE_URL || null,
      fallbackModels: (process.env.LLM_FALLBACK_MODELS || '').split(',').filter(Boolean),
    },
    embeddings: {
      provider: process.env.EMBEDDING_PROVIDER || 'hash',
      dimensions: parseInt(process.env.EMBEDDING_DIMENSIONS || '384', 10),
      model: process.env.EMBEDDING_MODEL || 'BAAI/bge-small-en-v1.5',
      baseUrl: process.env.EMBEDDING_BASE_URL || null,
      apiKey: process.env.EMBEDDING_API_KEY || null,
    },
    retrieval: {
      topK: parseInt(process.env.RETRIEVAL_TOP_K || '20', 10),
      rerankTopK: parseInt(process.env.RETRIEVAL_RERANK_TOP_K || '8', 10),
      finalContextK: parseInt(process.env.RETRIEVAL_FINAL_CONTEXT_K || '5', 10),
      denseWeight: parseFloat(process.env.RETRIEVAL_DENSE_WEIGHT || '0.55'),
      sparseWeight: parseFloat(process.env.RETRIEVAL_SPARSE_WEIGHT || '0.45'),
      reranker: process.env.RERANKER_TYPE || 'local',
    },
    chunking: {
      maxTokens: parseInt(process.env.CHUNKING_MAX_TOKENS || '320', 10),
      overlapTokens: parseInt(process.env.CHUNKING_OVERLAP_TOKENS || '48', 10),
      semanticChunking: process.env.CHUNKING_SEMANTIC === 'true',
      semanticSimilarityThreshold: parseFloat(process.env.CHUNKING_SEMANTIC_THRESHOLD || '0.75'),
    },
    qdrant: {
      host: process.env.QDRANT_HOST || 'localhost',
      port: parseInt(process.env.QDRANT_PORT || '6333', 10),
      apiKey: process.env.QDRANT_API_KEY || '',
      https: process.env.QDRANT_HTTPS === 'true',
    },
    rateLimit: {
      enabled: process.env.RATE_LIMIT_ENABLED !== 'false',
      requestsPerMinute: parseInt(process.env.RATE_LIMIT_RPM || '60', 10),
    },
    security: {
      adminJwtSecret: process.env.ADMIN_JWT_SECRET || '',
      adminPassword: process.env.ADMIN_PASSWORD || 'admin',
      corsOrigins: (process.env.CORS_ORIGINS || '*').split(','),
    },
  };
}

export function tenantConfigFromRow(tenant: any, rootDir: string): AppConfig {
  return {
    port: parseInt(process.env.PORT || '3001', 10),
    logLevel: process.env.LOG_LEVEL || 'info',
    tenantId: tenant.tenantId,
    defaultKb: 'default',
    sessionMemoryLimit: tenant.sessionMemoryLimit ?? 8,
    chatRetentionDays: tenant.chatRetentionDays ?? 30,
    rootDir,
    llm: {
      provider: tenant.llmProvider || 'gemini',
      apiKey: tenant.llmApiKey || '',
      model: tenant.llmModel || 'gemini-2.5-flash-lite',
      baseUrl: tenant.llmBaseUrl || null,
      fallbackModels: [],
    },
    embeddings: {
      provider: tenant.embeddingProvider || 'hash',
      dimensions: tenant.embeddingDimensions ?? 384,
      model: tenant.embeddingModel || 'BAAI/bge-small-en-v1.5',
      baseUrl: tenant.embeddingBaseUrl || null,
      apiKey: tenant.embeddingApiKey || null,
    },
    retrieval: {
      topK: tenant.retrievalTopK ?? 20,
      rerankTopK: tenant.retrievalRerankTopK ?? 8,
      finalContextK: tenant.retrievalFinalContextK ?? 5,
      denseWeight: tenant.retrievalDenseWeight ?? 0.55,
      sparseWeight: tenant.retrievalSparseWeight ?? 0.45,
      reranker: tenant.rerankerType || 'local',
    },
    chunking: {
      maxTokens: tenant.chunkingMaxTokens ?? 320,
      overlapTokens: tenant.chunkingOverlapTokens ?? 48,
      semanticChunking: tenant.chunkingSemantic ?? false,
      semanticSimilarityThreshold: tenant.chunkingSemanticThreshold ?? 0.75,
    },
    qdrant: {
      host: process.env.QDRANT_HOST || 'localhost',
      port: parseInt(process.env.QDRANT_PORT || '6333', 10),
      apiKey: process.env.QDRANT_API_KEY || '',
      https: process.env.QDRANT_HTTPS === 'true',
    },
    rateLimit: {
      enabled: true,
      requestsPerMinute: 60,
    },
    security: {
      adminJwtSecret: process.env.ADMIN_JWT_SECRET || '',
      adminPassword: process.env.ADMIN_PASSWORD || 'admin',
      corsOrigins: ['*'],
    },
  };
}
