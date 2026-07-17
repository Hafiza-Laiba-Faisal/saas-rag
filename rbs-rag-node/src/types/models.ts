export interface Metadata {
  [key: string]: any;
}

export interface LoadedDocument {
  documentId: string;
  path: string;
  name: string;
  documentType: string;
  text: string;
  metadata: Metadata;
  ocrApplied: boolean;
  ocrEngine: string | null;
  pageCount: number | null;
}

export interface Chunk {
  chunkId: string;
  documentId: string;
  text: string;
  metadata: Metadata;
  embedding: number[];
  ordinal: number;
}

export interface SearchResult {
  chunk: Chunk;
  score: number;
  denseScore: number;
  sparseScore: number;
  rerankScore: number;
}

export interface IngestSummary {
  documents: number;
  chunks: number;
  skipped: number;
  errors: string[];
}

export interface RetrievalValidation {
  sufficient: boolean;
  confidence: string;
  reasons: string[];
  citationQuality: number;
  answerCompleteness: number;
  confidenceScore: number;
}

export interface Citation {
  index: number;
  documentName: string;
  section: string | null;
  chunkId: string;
}

export interface Answer {
  text: string;
  citations: Citation[];
  validation: RetrievalValidation;
  contexts: SearchResult[];
  profile: Record<string, any>;
  streaming: boolean;
}

export interface StreamingChunk {
  text: string;
  done: boolean;
  error?: string | null;
  citations?: Citation[] | null;
}

export interface HealthStatus {
  status: string;
  db: string;
  qdrant: string;
  llm: string;
  embeddings: string;
  version: string;
  uptimeSeconds: number;
  totalDocuments: number;
  totalChunks: number;
}

export interface ChatRequest {
  query: string;
  sessionId: string;
  userId: string;
  filters?: Record<string, string> | null;
  systemPrompt?: string | null;
}

export interface TenantOnboardRequest {
  tenantId: string;
  name: string;
  subscriptionTier: string;
  monthlyFee: number;
  llmProvider: string;
  llmModel: string;
  llmApiKey: string;
  llmBaseUrl?: string | null;
  embeddingProvider: string;
  embeddingModel: string;
  embeddingDimensions: number;
  embeddingBaseUrl?: string | null;
  embeddingApiKey?: string | null;
  retrievalTopK: number;
  retrievalRerankTopK: number;
  retrievalFinalContextK: number;
  retrievalDenseWeight: number;
  retrievalSparseWeight: number;
  chunkingMaxTokens: number;
  chunkingOverlapTokens: number;
  chunkingSemantic: boolean;
  chunkingSemanticThreshold: number;
  rerankerType: string;
  sessionMemoryLimit: number;
  chatRetentionDays: number;
  systemPrompt?: string | null;
}

export interface ScrapeRequest {
  url: string;
  crawl: boolean;
  maxPages: number;
  maxDepth: number;
  fullSite: boolean;
}
