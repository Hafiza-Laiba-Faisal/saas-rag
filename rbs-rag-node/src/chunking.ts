import crypto from 'crypto';
import { LoadedDocument, Chunk } from './types/models.js';

const HEADING_RE = /^\s{0,3}(#{1,6})\s+(.+?)\s*$/gm;

export class HierarchicalChunker {
  maxTokens: number;
  overlapTokens: number;

  constructor(maxTokens = 320, overlapTokens = 48) {
    this.maxTokens = maxTokens;
    this.overlapTokens = overlapTokens;
  }

  chunk(document: LoadedDocument, tenantId: string, knowledgeBaseId: string): Chunk[] {
    const chunks: Chunk[] = [];
    let ordinal = 0;

    for (const [section, text] of splitSections(document.text)) {
      for (const piece of this.splitToTokenWindows(text)) {
        if (!piece.trim()) continue;
        const metadata = {
          ...document.metadata,
          tenant_id: tenantId,
          knowledge_base_id: knowledgeBaseId,
          document_id: document.documentId,
          document_name: document.name,
          document_type: document.documentType,
          section,
          chunk_ordinal: ordinal,
        };
        const chunkId = crypto
          .createHash('sha1')
          .update(`${document.documentId}:${ordinal}:${piece}`)
          .digest('hex');
        chunks.push({
          chunkId,
          documentId: document.documentId,
          text: piece,
          metadata,
          embedding: [],
          ordinal,
        });
        ordinal++;
      }
    }
    return chunks;
  }

  splitToTokenWindows(text: string): string[] {
    const paragraphs = text
      .split(/\n\s*\n|\r?\n/)
      .map(p => p.trim())
      .filter(Boolean);
    const windows: string[] = [];
    let current: string[] = [];

    for (const paragraph of paragraphs) {
      const words = paragraph.split(/\s+/);
      if (words.length > this.maxTokens) {
        if (current.length) {
          windows.push(current.join(' '));
          current = [];
        }
        windows.push(...this.windowWords(words));
        continue;
      }
      if (current.length + words.length <= this.maxTokens) {
        current.push(...words);
      } else {
        if (current.length) windows.push(current.join(' '));
        const overlap = this.overlapTokens > 0 ? current.slice(-this.overlapTokens) : [];
        current = [...overlap, ...words];
        if (current.length > this.maxTokens) {
          windows.push(...this.windowWords(current));
          current = [];
        }
      }
    }
    if (current.length) windows.push(current.join(' '));
    return windows;
  }

  private windowWords(words: string[]): string[] {
    const step = Math.max(this.maxTokens - this.overlapTokens, 1);
    const output: string[] = [];
    for (let start = 0; start < words.length; start += step) {
      const window = words.slice(start, start + this.maxTokens);
      if (window.length) output.push(window.join(' '));
      if (start + this.maxTokens >= words.length) break;
    }
    return output;
  }
}

function splitSections(text: string): Array<[string, string]> {
  const sections: Array<[string, string]> = [];
  let currentTitle = 'General';
  let currentLines: string[] = [];
  const lines = text.split('\n');

  for (const line of lines) {
    const match = HEADING_RE.exec(line);
    HEADING_RE.lastIndex = 0;
    if (match) {
      if (currentLines.length) {
        sections.push([currentTitle, currentLines.join('\n').trim()]);
        currentLines = [];
      }
      currentTitle = match[2].trim();
    } else {
      currentLines.push(line);
    }
  }
  if (currentLines.length) {
    sections.push([currentTitle, currentLines.join('\n').trim()]);
  }
  if (!sections.length && text.trim()) {
    sections.push(['General', text.trim()]);
  }
  return sections;
}

export function createChunker(config: {
  maxTokens: number;
  overlapTokens: number;
  semanticChunking: boolean;
  semanticSimilarityThreshold: number;
}): HierarchicalChunker {
  return new HierarchicalChunker(config.maxTokens, config.overlapTokens);
}
