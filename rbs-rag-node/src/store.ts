import { PrismaClient } from '@prisma/client';
import { Chunk, LoadedDocument } from './types/models.js';

export class DbStore {
  private prisma: PrismaClient;

  constructor(prisma: PrismaClient) {
    this.prisma = prisma;
  }

  async upsertDocument(
    document: LoadedDocument,
    tenantId: string,
    knowledgeBaseId: string,
    source = 'upload',
    sourceUrl?: string | null
  ): Promise<void> {
    const metadata: Record<string, any> = { ...document.metadata, tenant_id: tenantId, knowledge_base_id: knowledgeBaseId, source };
    if (sourceUrl) metadata['source_url'] = sourceUrl;

    await this.prisma.$executeRawUnsafe(
      `DELETE FROM chunks WHERE document_id = ?`,
      [document.documentId]
    );

    await this.prisma.document.upsert({
      where: { documentId: document.documentId },
      update: {
        path: document.path,
        name: document.name,
        documentType: document.documentType,
        text: document.text,
        metadataJson: JSON.stringify(metadata),
        ocrApplied: document.ocrApplied,
        ocrEngine: document.ocrEngine,
        pageCount: document.pageCount,
        source,
        sourceUrl: sourceUrl || null,
      },
      create: {
        documentId: document.documentId,
        tenantId,
        knowledgeBaseId,
        path: document.path,
        name: document.name,
        documentType: document.documentType,
        text: document.text,
        metadataJson: JSON.stringify(metadata),
        ocrApplied: document.ocrApplied,
        ocrEngine: document.ocrEngine,
        pageCount: document.pageCount,
        source,
        sourceUrl: sourceUrl || null,
      },
    });
  }

  async deleteDocument(documentId: string): Promise<void> {
    await this.prisma.chunk.deleteMany({ where: { documentId } });
    await this.prisma.document.delete({ where: { documentId } }).catch(() => {});
  }

  async getDocument(documentId: string): Promise<any | null> {
    const doc = await this.prisma.document.findUnique({ where: { documentId } });
    if (!doc) return null;
    return { ...doc, metadata: JSON.parse(doc.metadataJson) };
  }

  async upsertChunks(chunks: Chunk[]): Promise<void> {
    for (const chunk of chunks) {
      await this.prisma.chunk.upsert({
        where: { chunkId: chunk.chunkId },
        update: {
          text: chunk.text,
          metadataJson: JSON.stringify(chunk.metadata),
          embeddingJson: JSON.stringify(chunk.embedding),
          ordinal: chunk.ordinal,
        },
        create: {
          chunkId: chunk.chunkId,
          documentId: chunk.documentId,
          tenantId: chunk.metadata.tenant_id || '',
          knowledgeBaseId: chunk.metadata.knowledge_base_id || 'default',
          ordinal: chunk.ordinal,
          text: chunk.text,
          metadataJson: JSON.stringify(chunk.metadata),
          embeddingJson: JSON.stringify(chunk.embedding),
        },
      });
    }
  }

  async deleteChunks(chunkIds: string[]): Promise<void> {
    if (!chunkIds.length) return;
    await this.prisma.chunk.deleteMany({
      where: { chunkId: { in: chunkIds } },
    });
  }

  async listChunks(tenantId: string, knowledgeBaseId: string, filters?: Record<string, string>): Promise<Chunk[]> {
    const rows = await this.prisma.chunk.findMany({
      where: { tenantId, knowledgeBaseId },
      orderBy: { ordinal: 'asc' },
    });
    let chunks = rows.map(rowToChunk);
    if (filters) {
      chunks = chunks.filter(c => metadataMatches(c.metadata, filters!));
    }
    return chunks;
  }

  async listDocuments(tenantId: string, knowledgeBaseId: string): Promise<any[]> {
    const rows = await this.prisma.document.findMany({
      where: { tenantId, knowledgeBaseId },
      orderBy: { name: 'asc' },
    });
    return rows.map(r => ({
      ...r,
      metadata: JSON.parse(r.metadataJson),
      ocrApplied: r.ocrApplied,
    }));
  }

  async countDocuments(tenantId: string, knowledgeBaseId: string): Promise<number> {
    return this.prisma.document.count({ where: { tenantId, knowledgeBaseId } });
  }

  async countChunks(tenantId: string, knowledgeBaseId: string): Promise<number> {
    return this.prisma.chunk.count({ where: { tenantId, knowledgeBaseId } });
  }

  async addSessionTurn(tenantId: string, sessionId: string, userId: string, role: string, content: string): Promise<void> {
    await this.prisma.sessionTurn.create({
      data: { tenantId, sessionId, userId, role, content },
    });
  }

  async getSessionMemory(tenantId: string, sessionId: string, userId: string, limit = 8): Promise<string> {
    const rows = await this.prisma.sessionTurn.findMany({
      where: { tenantId, sessionId, userId },
      orderBy: { id: 'desc' },
      take: limit,
      select: { role: true, content: true },
    });
    const ordered = rows.reverse();
    return ordered.map(r => `${r.role}: ${r.content}`).join('\n');
  }

  async listSessions(tenantId: string): Promise<any[]> {
    return this.prisma.sessionTurn.groupBy({
      by: ['sessionId', 'userId'],
      where: { tenantId },
      _count: { id: true },
      _max: { createdAt: true },
    }).then(rows => rows.map(r => ({
      sessionId: r.sessionId,
      userId: r.userId,
      turns: r._count.id,
      lastTurnAt: r._max.createdAt,
    })));
  }

  async getSessionTurns(tenantId: string, sessionId: string): Promise<any[]> {
    return this.prisma.sessionTurn.findMany({
      where: { tenantId, sessionId },
      orderBy: { id: 'asc' },
      select: { role: true, content: true, createdAt: true },
    });
  }

  async deleteSession(tenantId: string, sessionId: string): Promise<void> {
    await this.prisma.sessionTurn.deleteMany({ where: { tenantId, sessionId } });
  }

  async purgeExpiredSessions(tenantId: string, retentionDays: number): Promise<number> {
    if (retentionDays <= 0) return 0;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - retentionDays);
    const result = await this.prisma.sessionTurn.deleteMany({
      where: { tenantId, createdAt: { lt: cutoff } },
    });
    return result.count;
  }
}

function rowToChunk(row: any): Chunk {
  return {
    chunkId: row.chunkId,
    documentId: row.documentId,
    text: row.text,
    metadata: JSON.parse(row.metadataJson),
    embedding: JSON.parse(row.embeddingJson),
    ordinal: row.ordinal,
  };
}

function metadataMatches(metadata: Record<string, any>, filters: Record<string, string>): boolean {
  for (const [key, expected] of Object.entries(filters)) {
    const actual = metadata[key];
    if (Array.isArray(actual)) {
      if (!actual.map(String).includes(expected)) return false;
    } else if (String(actual) !== expected) {
      return false;
    }
  }
  return true;
}
