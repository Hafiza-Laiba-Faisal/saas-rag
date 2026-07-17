import crypto from 'crypto';
import { l2Normalize, tokenize } from './text.js';

export interface EmbeddingProvider {
  dimensions: number;
  embed(texts: string[]): Promise<number[][]>;
}

export class HashEmbeddingProvider implements EmbeddingProvider {
  dimensions: number;

  constructor(dimensions = 384) {
    this.dimensions = dimensions;
  }

  async embed(texts: string[]): Promise<number[][]> {
    return texts.map(t => this.embedOne(t));
  }

  private embedOne(text: string): number[] {
    const vector = new Array(this.dimensions).fill(0);
    for (const token of tokenize(text)) {
      const hash = crypto.createHash('sha256').update(token, 'utf-8').digest();
      const index = hash.readUInt32BE(0) % this.dimensions;
      const sign = hash[4] % 2 === 0 ? 1 : -1;
      vector[index] += sign;
    }
    return l2Normalize(vector);
  }
}

export class OpenAIEmbeddingProvider implements EmbeddingProvider {
  private apiKey: string;
  private model: string;
  dimensions: number;

  constructor(apiKey: string, model = 'text-embedding-3-small', dimensions = 1536) {
    this.apiKey = apiKey;
    this.model = model;
    this.dimensions = dimensions;
  }

  async embed(texts: string[]): Promise<number[][]> {
    const url = 'https://api.openai.com/v1/embeddings';
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ input: texts, model: this.model }),
    });
    if (!resp.ok) {
      throw new Error(`OpenAI embedding failed: ${await resp.text()}`);
    }
    const data = await resp.json() as any;
    data.data.sort((a: any, b: any) => a.index - b.index);
    return data.data.map((item: any) => item.embedding);
  }
}

export class GeminiEmbeddingProvider implements EmbeddingProvider {
  private apiKey: string;
  private model: string;
  dimensions: number;

  constructor(apiKey: string, model = 'text-embedding-004', dimensions = 768) {
    this.apiKey = apiKey;
    this.model = model;
    this.dimensions = dimensions;
  }

  async embed(texts: string[]): Promise<number[][]> {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${this.model}:batchEmbedContents?key=${this.apiKey}`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requests: texts.map(text => ({
          model: `models/${this.model}`,
          content: { parts: [{ text }] },
        })),
      }),
    });
    if (!resp.ok) {
      throw new Error(`Gemini embedding failed: ${await resp.text()}`);
    }
    const data = await resp.json() as any;
    return data.embeddings.map((item: any) => item.values);
  }
}

export function createEmbeddingProvider(config: {
  provider: string;
  dimensions: number;
  model: string;
  apiKey: string | null;
  baseUrl: string | null;
}): EmbeddingProvider {
  const { provider, dimensions, model, apiKey } = config;
  if (provider === 'hash') {
    return new HashEmbeddingProvider(dimensions);
  }
  if (provider === 'openai' || provider === 'openai_compatible') {
    return new OpenAIEmbeddingProvider(apiKey || '', model, dimensions);
  }
  if (provider === 'gemini') {
    return new GeminiEmbeddingProvider(apiKey || '', model, dimensions);
  }
  // Fallback to hash
  return new HashEmbeddingProvider(dimensions);
}
