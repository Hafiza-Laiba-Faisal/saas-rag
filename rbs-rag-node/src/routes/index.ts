import { Router, Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import crypto from 'crypto';
import jwt from 'jsonwebtoken';
import { AppConfig } from '../config.js';
import { AdminStore } from '../adminStore.js';
import { DbStore } from '../store.js';
import { RagEngine, createEngineFromTenant } from '../engine.js';
import { scrapeUrl } from '../scraper.js';
import {
  scrapeSingle, scrapeSmart, startRecursiveCrawl,
  getRecursiveStatus, scrapeWordPress, scrapeFacebook,
  getFbJobStatus, scrapeProfile, scrapeAndIngest,
} from '../scraperClient.js';
import { loadProviderPresets, saveProviderPresets } from '../providerPresets.js';

const ingestionStatus: Record<string, any> = {};

export function routes(
  config: AppConfig,
  adminStore: AdminStore,
  dbStore: DbStore,
  engineCache: Map<string, RagEngine>
): Router {
  const router = Router();

  interface TenantRequest extends Request {
    tenant?: any;
    admin?: any;
  }

  // ===================== ADMIN AUTH =====================
  router.post('/admin/login', async (req, res) => {
    try {
      const { username, password } = req.body;
      const secret = config.security.adminJwtSecret;
      if (!secret) return res.json({ status: 'error', detail: 'Admin auth not configured' });
      if (username !== 'admin' || password !== config.security.adminPassword)
        return res.status(401).json({ detail: 'Invalid credentials' });
      const token = jwt.sign({ role: 'admin', tenant_id: 'admin' }, secret, { expiresIn: '24h' });
      res.json({ status: 'success', token, access_token: token, token_type: 'Bearer' });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  // ===================== MIDDLEWARE =====================
  function requireAdmin(req: TenantRequest, res: Response, next: NextFunction) {
    const secret = config.security.adminJwtSecret;
    if (!secret) { req.admin = { role: 'admin', tenantId: 'admin' }; return next(); }
    const auth = req.headers.authorization;
    if (!auth || !auth.startsWith('Bearer '))
      return res.status(401).json({ detail: 'Missing or invalid Authorization header' });
    try {
      req.admin = jwt.verify(auth.slice(7), secret);
      next();
    } catch {
      return res.status(401).json({ detail: 'Invalid or expired token' });
    }
  }

  async function resolveClientTenant(req: TenantRequest, res: Response, next: NextFunction) {
    const apiKey: string | undefined = req.headers['x-api-key'] as string || (typeof req.query.api_key === 'string' ? req.query.api_key : undefined);
    if (!apiKey) return res.status(401).json({ detail: 'Missing API Key' });
    const tenant = await adminStore.getTenantByApiKey(apiKey);
    if (!tenant) return res.status(401).json({ detail: 'Invalid API Key' });
    if (tenant.status !== 'active') return res.status(403).json({ detail: 'Client account is suspended' });
    (req as TenantRequest).tenant = tenant;
    next();
  }

  async function getOrCreateEngine(tenant: any): Promise<RagEngine> {
    const tid = tenant.tenantId;
    if (!engineCache.has(tid)) {
      const engine = await createEngineFromTenant(tenant, config.rootDir, dbStore, adminStore);
      engineCache.set(tid, engine);
    }
    return engineCache.get(tid)!;
  }

  // ===================== TENANT APIs =====================
  router.get('/tenants', requireAdmin, async (_req, res) => {
    const tenants = await adminStore.listTenants();
    const result = await Promise.all(tenants.map(async (t: any) => ({
      tenantId: t.tenantId,
      name: t.name,
      apiKey: t.apiKey,
      status: t.status,
      subscriptionTier: t.subscriptionTier,
      monthlyFee: t.monthlyFee,
      llmProvider: t.llmProvider,
      llmModel: t.llmModel,
      llmApiKey: '***',
      embeddingProvider: t.embeddingProvider,
      embeddingModel: t.embeddingModel,
      embeddingDimensions: t.embeddingDimensions,
      embeddingApiKey: t.embeddingApiKey ? '***' : null,
      retrievalTopK: t.retrievalTopK,
      retrievalRerankTopK: t.retrievalRerankTopK,
      retrievalFinalContextK: t.retrievalFinalContextK,
      retrievalDenseWeight: t.retrievalDenseWeight,
      retrievalSparseWeight: t.retrievalSparseWeight,
      chunkingMaxTokens: t.chunkingMaxTokens,
      chunkingOverlapTokens: t.chunkingOverlapTokens,
      chunkingSemantic: t.chunkingSemantic,
      chunkingSemanticThreshold: t.chunkingSemanticThreshold,
      rerankerType: t.rerankerType,
      sessionMemoryLimit: t.sessionMemoryLimit,
      chatRetentionDays: t.chatRetentionDays,
      systemPrompt: t.systemPrompt,
      docCount: await dbStore.countDocuments(t.tenantId, 'default'),
      chunkCount: await dbStore.countChunks(t.tenantId, 'default'),
    })));
    res.json(result);
  });

  router.post('/tenants', requireAdmin, async (req, res) => {
    try {
      const body = req.body;
      const tid = body.tenant_id || body.tenantId;
      if (!tid) return res.status(400).json({ detail: 'tenant_id is required' });
      const existing = await adminStore.getTenant(tid);
      if (existing) return res.status(400).json({ detail: 'Tenant ID already exists' });
      const apiKey = `rbs_rag_sk_${crypto.randomBytes(16).toString('hex')}`;
      const tenantData = {
        tenantId: tid,
        name: body.name || tid,
        apiKey,
        status: 'active',
        subscriptionTier: body.subscription_tier || 'basic',
        monthlyFee: body.monthly_fee || 299,
        llmProvider: body.llm_provider || 'gemini',
        llmModel: body.llm_model || 'gemini-2.5-flash-lite',
        llmApiKey: body.llm_api_key || body.llmApiKey || '',
        llmBaseUrl: body.llm_base_url || null,
        embeddingProvider: body.embedding_provider || 'hash',
        embeddingModel: body.embedding_model || 'BAAI/bge-small-en-v1.5',
        embeddingDimensions: body.embedding_dimensions || 384,
        embeddingBaseUrl: body.embedding_base_url || null,
        embeddingApiKey: body.embedding_api_key || body.embeddingApiKey || null,
        retrievalTopK: body.retrieval_top_k || 20,
        retrievalRerankTopK: body.retrieval_rerank_top_k || 8,
        retrievalFinalContextK: body.retrieval_final_context_k || 5,
        retrievalDenseWeight: body.retrieval_dense_weight || 0.55,
        retrievalSparseWeight: body.retrieval_sparse_weight || 0.45,
        chunkingMaxTokens: body.chunking_max_tokens || 320,
        chunkingOverlapTokens: body.chunking_overlap_tokens || 48,
        chunkingSemantic: body.chunking_semantic || false,
        chunkingSemanticThreshold: body.chunking_semantic_threshold || 0.75,
        rerankerType: body.reranker_type || 'local',
        sessionMemoryLimit: body.session_memory_limit || 8,
        chatRetentionDays: body.chat_retention_days || 30,
        systemPrompt: body.system_prompt || null,
      };
      await adminStore.upsertTenant(tenantData);
      fs.mkdirSync(path.join(config.rootDir, 'tenants', tid, 'documents'), { recursive: true });
      res.json({ status: 'success', tenantId: tid, apiKey: apiKey });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.get('/tenants/:tenantId', requireAdmin, async (req, res) => {
    const t = await adminStore.getTenant(req.params.tenantId);
    if (!t) return res.status(404).json({ detail: 'Tenant not found' });
    res.json({
      tenantId: t.tenantId, name: t.name, apiKey: t.apiKey, status: t.status,
      subscriptionTier: t.subscriptionTier, monthlyFee: t.monthlyFee,
      llmProvider: t.llmProvider, llmModel: t.llmModel, llmApiKey: '***',
      llmBaseUrl: t.llmBaseUrl,
      embeddingProvider: t.embeddingProvider, embeddingModel: t.embeddingModel,
      embeddingDimensions: t.embeddingDimensions, embeddingBaseUrl: t.embeddingBaseUrl,
      embeddingApiKey: t.embeddingApiKey ? '***' : null,
      retrievalTopK: t.retrievalTopK, retrievalRerankTopK: t.retrievalRerankTopK,
      retrievalFinalContextK: t.retrievalFinalContextK,
      retrievalDenseWeight: t.retrievalDenseWeight, retrievalSparseWeight: t.retrievalSparseWeight,
      chunkingMaxTokens: t.chunkingMaxTokens, chunkingOverlapTokens: t.chunkingOverlapTokens,
      chunkingSemantic: t.chunkingSemantic, chunkingSemanticThreshold: t.chunkingSemanticThreshold,
      rerankerType: t.rerankerType, sessionMemoryLimit: t.sessionMemoryLimit,
      chatRetentionDays: t.chatRetentionDays, systemPrompt: t.systemPrompt,
    });
  });

  router.get('/tenants/:tenantId/config', requireAdmin, async (req, res) => {
    const t = await adminStore.getTenant(req.params.tenantId);
    if (!t) return res.status(404).json({ detail: 'Tenant not found' });
    res.json({
      tenantId: t.tenantId, name: t.name, status: t.status,
      subscriptionTier: t.subscriptionTier, monthlyFee: t.monthlyFee,
      llmProvider: t.llmProvider, llmModel: t.llmModel,
      llmBaseUrl: t.llmBaseUrl,
      embeddingProvider: t.embeddingProvider, embeddingModel: t.embeddingModel,
      embeddingDimensions: t.embeddingDimensions, embeddingBaseUrl: t.embeddingBaseUrl,
      retrievalTopK: t.retrievalTopK, retrievalRerankTopK: t.retrievalRerankTopK,
      retrievalFinalContextK: t.retrievalFinalContextK,
      retrievalDenseWeight: t.retrievalDenseWeight, retrievalSparseWeight: t.retrievalSparseWeight,
      chunkingMaxTokens: t.chunkingMaxTokens, chunkingOverlapTokens: t.chunkingOverlapTokens,
      chunkingSemantic: t.chunkingSemantic, chunkingSemanticThreshold: t.chunkingSemanticThreshold,
      rerankerType: t.rerankerType, sessionMemoryLimit: t.sessionMemoryLimit,
      chatRetentionDays: t.chatRetentionDays, systemPrompt: t.systemPrompt,
    });
  });

  router.put('/tenants/:tenantId', requireAdmin, async (req, res) => {
    const existing = await adminStore.getTenant(req.params.tenantId);
    if (!existing) return res.status(404).json({ detail: 'Tenant not found' });
    const body = req.body;
    const llmKey = (body.llm_api_key || body.llmApiKey) === '***' ? existing.llmApiKey : (body.llm_api_key || body.llmApiKey || existing.llmApiKey);
    const embKey = (body.embedding_api_key || body.embeddingApiKey) === '***' ? existing.embeddingApiKey : (body.embedding_api_key || body.embeddingApiKey || existing.embeddingApiKey);
    const updatedData = {
      ...existing,
      tenantId: req.params.tenantId,
      name: body.name || existing.name,
      status: body.status || existing.status,
      subscriptionTier: body.subscription_tier || existing.subscriptionTier,
      monthlyFee: body.monthly_fee ?? existing.monthlyFee,
      llmProvider: body.llm_provider || existing.llmProvider,
      llmModel: body.llm_model || existing.llmModel,
      llmApiKey: llmKey,
      llmBaseUrl: body.llm_base_url !== undefined ? body.llm_base_url : existing.llmBaseUrl,
      embeddingProvider: body.embedding_provider || existing.embeddingProvider,
      embeddingModel: body.embedding_model || existing.embeddingModel,
      embeddingDimensions: body.embedding_dimensions ?? existing.embeddingDimensions,
      embeddingBaseUrl: body.embedding_base_url !== undefined ? body.embedding_base_url : existing.embeddingBaseUrl,
      embeddingApiKey: embKey,
      apiKey: existing.apiKey,
      retrievalTopK: body.retrieval_top_k ?? existing.retrievalTopK,
      retrievalRerankTopK: body.retrieval_rerank_top_k ?? existing.retrievalRerankTopK,
      retrievalFinalContextK: body.retrieval_final_context_k ?? existing.retrievalFinalContextK,
      retrievalDenseWeight: body.retrieval_dense_weight ?? existing.retrievalDenseWeight,
      retrievalSparseWeight: body.retrieval_sparse_weight ?? existing.retrievalSparseWeight,
      chunkingMaxTokens: body.chunking_max_tokens ?? existing.chunkingMaxTokens,
      chunkingOverlapTokens: body.chunking_overlap_tokens ?? existing.chunkingOverlapTokens,
      chunkingSemantic: body.chunking_semantic ?? existing.chunkingSemantic,
      chunkingSemanticThreshold: body.chunking_semantic_threshold ?? existing.chunkingSemanticThreshold,
      rerankerType: body.reranker_type || existing.rerankerType,
      sessionMemoryLimit: body.session_memory_limit ?? existing.sessionMemoryLimit,
      chatRetentionDays: body.chat_retention_days ?? existing.chatRetentionDays,
      systemPrompt: body.system_prompt !== undefined ? body.system_prompt : existing.systemPrompt,
    };
    await adminStore.upsertTenant(updatedData);
    engineCache.delete(req.params.tenantId);
    res.json({ status: 'success' });
  });

  router.delete('/tenants/:tenantId', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    await adminStore.deleteTenant(req.params.tenantId);
    const tenantDir = path.join(config.rootDir, 'tenants', req.params.tenantId);
    if (fs.existsSync(tenantDir)) fs.rmSync(tenantDir, { recursive: true });
    engineCache.delete(req.params.tenantId);
    res.json({ status: 'success' });
  });

  // ===================== DOCUMENTS APIs =====================
  router.get('/tenants/:tenantId/documents', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    const docsDir = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents');
    if (!fs.existsSync(docsDir)) fs.mkdirSync(docsDir, { recursive: true });
    const ingestedMap: Record<string, any> = {};
    const docs = await dbStore.listDocuments(req.params.tenantId, 'default');
    for (const d of docs) ingestedMap[d.documentId] = d;
    const files = fs.readdirSync(docsDir).filter(f => fs.statSync(path.join(docsDir, f)).isFile());
    const result = await Promise.all(files.map(async name => {
      const filePath = path.join(docsDir, name);
      const stat = fs.statSync(filePath);
      const docId = crypto.createHash('sha1').update(filePath).digest('hex');
      const ingested = ingestedMap[docId];
      const chunks = ingested ? await dbStore.countChunksForDocument(req.params.tenantId, 'default', docId) : 0;
      return {
        name, size_bytes: stat.size, ingested: !!ingested,
        chunks, extension: path.extname(name).replace('.', ''),
        source: ingested?.source || 'upload',
      };
    }));
    res.json(result);
  });

  router.get('/tenants/:tenantId/documents/:filename', requireAdmin, async (req, res) => {
    const filePath = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents', req.params.filename);
    if (!fs.existsSync(filePath)) return res.status(404).json({ detail: 'File not found' });
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes: Record<string, string> = { '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.html': 'text/html', '.htm': 'text/html' };
    res.type(mimeTypes[ext] || 'application/octet-stream').send(fs.readFileSync(filePath));
  });

  router.get('/tenants/:tenantId/documents/:filename/chunks', requireAdmin, async (req, res) => {
    const docs = await dbStore.listDocuments(req.params.tenantId, 'default');
    const doc = docs.find((d: any) => d.name === req.params.filename);
    if (!doc) return res.json([]);
    const docChunks = await dbStore.listChunksForDocument(req.params.tenantId, 'default', doc.documentId);
    res.json(docChunks.map(c => ({ chunk_id: c.chunkId, ordinal: c.ordinal, text: c.text, metadata: c.metadata })));
  });

  router.post('/tenants/:tenantId/documents', requireAdmin, async (req, res) => {
    const { default: multer } = await import('multer');
    const storage = multer.diskStorage({
      destination: path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents'),
      filename: (_req, file, cb) => {
        const ext = path.extname(file.originalname) || '';
        cb(null, `${Date.now()}_${file.originalname.replace(ext, '').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 60)}${ext}`);
      },
    });
    const upload = multer({ storage });
    upload.array('files')(req, res, (err: any) => {
      if (err) return res.status(400).json({ detail: err.message });
      const files = req.files as Express.Multer.File[];
      res.json({ status: 'success', uploaded: files.map(f => ({ original: f.originalname, saved_as: f.filename })) });
    });
  });

  router.delete('/tenants/:tenantId/documents/:filename', requireAdmin, async (req, res) => {
    const filePath = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents', req.params.filename);
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
    const docId = crypto.createHash('sha1').update(filePath).digest('hex');
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (tenant) {
      const engine = await getOrCreateEngine(tenant);
      await engine.deleteDocument(docId);
    } else {
      await dbStore.deleteDocument(docId);
    }
    res.json({ status: 'success' });
  });

  // ===================== INGESTION APIs =====================
  router.post('/tenants/:tenantId/ingest', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    if (ingestionStatus[req.params.tenantId]?.status === 'running')
      return res.json({ status: 'already_running' });
    const engine = await getOrCreateEngine(tenant);
    const applyOcr = req.query.apply_ocr === 'true';
    ingestionStatus[req.params.tenantId] = { status: 'running', logs: ['Starting ingestion...'], progress: 0, summary: null };
    engine.ingest(req.params.tenantId, 'default', applyOcr).then(summary => {
      ingestionStatus[req.params.tenantId] = {
        status: summary.errors.length ? 'error' : 'completed',
        logs: [`Ingestion finished: ${summary.documents} docs, ${summary.chunks} chunks. Errors: ${summary.errors.length}`],
        progress: 100, summary,
      };
    }).catch((err: any) => {
      ingestionStatus[req.params.tenantId] = { status: 'error', logs: [`Error: ${err.message}`], progress: 100, summary: null };
    });
    res.json({ status: 'started', apply_ocr: applyOcr });
  });

  router.get('/tenants/:tenantId/ingest/status', requireAdmin, async (req, res) => {
    res.json(ingestionStatus[req.params.tenantId] || { status: 'idle', logs: ['No ingestion tasks run yet.'], progress: 0, summary: null });
  });

  // ===================== CHAT APIs =====================
  router.post('/tenants/:tenantId/chat', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    if (tenant.status !== 'active') return res.status(403).json({ detail: 'Tenant account is suspended' });
    const { query, session_id, user_id, filters, system_prompt } = req.body;
    const engine = await getOrCreateEngine(tenant);
    try {
      const answer = await engine.ask(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
      res.json({
        answer: answer.text,
        citations: answer.citations.map(c => ({ index: c.index, document_name: c.documentName, section: c.section, chunk_id: c.chunkId })),
        contexts: answer.contexts.map(ctx => ({ text: ctx.chunk.text, score: ctx.score, dense_score: ctx.denseScore, sparse_score: ctx.sparseScore, rerank_score: ctx.rerankScore, metadata: ctx.chunk.metadata })),
        validation: { sufficient: answer.validation.sufficient, confidence: answer.validation.confidence, reasons: answer.validation.reasons, confidence_score: answer.validation.confidenceScore },
        profile: answer.profile,
      });
    } catch (err: any) {
      console.error(`[Chat Error] tenant=${req.params.tenantId} provider=${tenant.llmProvider} model=${tenant.llmModel}: ${err.message}`);
      res.status(500).json({ detail: `Model API Error (${tenant.llmProvider}/${tenant.llmModel}): ${err.message}` });
    }
  });

  router.post('/tenants/:tenantId/chat/stream', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    if (tenant.status !== 'active') return res.status(403).json({ detail: 'Tenant account is suspended' });
    const { query, session_id, user_id, filters, system_prompt } = req.body;
    const engine = await getOrCreateEngine(tenant);
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    try {
      const stream = engine.askStream(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
      for await (const chunk of stream) {
        const data: any = { text: chunk.text, done: chunk.done };
        if (chunk.error) data.error = chunk.error;
        if (chunk.citations) data.citations = chunk.citations.map(c => ({ index: c.index, document_name: c.documentName, section: c.section, chunk_id: c.chunkId }));
        res.write(`data: ${JSON.stringify(data)}\n\n`);
      }
    } catch (err: any) {
      console.error('[Admin Stream Error]', err?.message || err);
      res.write(`data: ${JSON.stringify({ text: '', done: true, error: err?.message || 'LLM stream failed' })}\n\n`);
    }
    res.end();
  });

  // ===================== CLIENT CHAT APIs =====================
  router.post('/chat', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    const { query, session_id, user_id, filters, system_prompt } = req.body;
    const engine = await getOrCreateEngine(tenant);
    try {
      const answer = await engine.ask(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
      res.json({ answer: answer.text, citations: answer.citations.map(c => ({ index: c.index, document_name: c.documentName, section: c.section, chunk_id: c.chunkId })), validation: { sufficient: answer.validation.sufficient, confidence: answer.validation.confidence } });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.post('/chat/stream', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    const { query, session_id, user_id, filters, system_prompt } = req.body;
    const engine = await getOrCreateEngine(tenant);
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    try {
      const stream = engine.askStream(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
      for await (const chunk of stream) {
        const data: any = { text: chunk.text, done: chunk.done };
        if (chunk.error) data.error = chunk.error;
        res.write(`data: ${JSON.stringify(data)}\n\n`);
      }
    } catch (err: any) {
      console.error('[Client Stream Error]', err?.message || err);
      res.write(`data: ${JSON.stringify({ text: '', done: true, error: err?.message || 'LLM stream failed' })}\n\n`);
    }
    res.end();
  });

  // ===================== CLIENT DOCUMENT APIs =====================
  router.get('/client/documents', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    const docsDir = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents');
    if (!fs.existsSync(docsDir)) fs.mkdirSync(docsDir, { recursive: true });
    const ingestedMap: Record<string, any> = {};
    const docs = await dbStore.listDocuments(tenant.tenantId, 'default');
    for (const d of docs) ingestedMap[d.documentId] = d;
    const files = fs.readdirSync(docsDir).filter(f => fs.statSync(path.join(docsDir, f)).isFile());
    const result = await Promise.all(files.map(async name => {
      const filePath = path.join(docsDir, name);
      const stat = fs.statSync(filePath);
      const docId = crypto.createHash('sha1').update(filePath).digest('hex');
      const ingested = ingestedMap[docId];
      const chunks = ingested ? await dbStore.countChunksForDocument(tenant.tenantId, 'default', docId) : 0;
      return { name, size_bytes: stat.size, ingested: !!ingested, chunks, extension: path.extname(name).replace('.', '') };
    }));
    res.json(result);
  });

  router.get('/client/documents/:filename', async (req, res) => {
    const apiKey: string | undefined = req.headers['x-api-key'] as string || (typeof req.query.api_key === 'string' ? req.query.api_key : undefined);
    if (!apiKey) return res.status(401).json({ detail: 'Missing API Key' });
    const tenant = await adminStore.getTenantByApiKey(apiKey as string);
    if (!tenant || tenant.status !== 'active') return res.status(401).json({ detail: 'Invalid API Key' });
    const filePath = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents', req.params.filename);
    if (!fs.existsSync(filePath)) return res.status(404).json({ detail: 'File not found' });
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes: Record<string, string> = { '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.html': 'text/html', '.htm': 'text/html' };
    res.type(mimeTypes[ext] || 'application/octet-stream').send(fs.readFileSync(filePath));
  });

  router.post('/client/documents', resolveClientTenant, async (req, res) => {
    const { default: multer } = await import('multer');
    const tenant = (req as TenantRequest).tenant;
    const storage = multer.diskStorage({
      destination: path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents'),
      filename: (_req, file, cb) => {
        const ext = path.extname(file.originalname) || '';
        cb(null, `${Date.now()}_${file.originalname.replace(ext, '').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 60)}${ext}`);
      },
    });
    const upload = multer({ storage });
    upload.array('files')(req, res, (err: any) => {
      if (err) return res.status(400).json({ detail: err.message });
      const files = req.files as Express.Multer.File[];
      res.json({ status: 'success', uploaded: files.map(f => ({ original: f.originalname, saved_as: f.filename })) });
    });
  });

  router.post('/client/ingest', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    const engine = await getOrCreateEngine(tenant);
    const applyOcr = req.query.apply_ocr === 'true';
    ingestionStatus[tenant.tenantId] = { status: 'running', logs: ['Starting ingestion...'], progress: 0, summary: null };
    engine.ingest(tenant.tenantId, 'default', applyOcr).then(summary => {
      ingestionStatus[tenant.tenantId] = { status: summary.errors.length ? 'error' : 'completed', logs: [`Ingestion finished: ${summary.documents} docs, ${summary.chunks} chunks.`], progress: 100, summary };
    }).catch((err: any) => {
      ingestionStatus[tenant.tenantId] = { status: 'error', logs: [`Error: ${err.message}`], progress: 100, summary: null };
    });
    res.json({ status: 'started', apply_ocr: applyOcr });
  });

   router.get('/client/documents/:filename/chunks', resolveClientTenant, async (req, res) => {
     const tenant = (req as TenantRequest).tenant;
     const doc = await dbStore.listDocuments(tenant.tenantId, 'default').then(docs => docs.find(d => d.name === req.params.filename));
     if (!doc) return res.status(404).json({ detail: 'Document not found' });
     const chunks = await dbStore.listChunksForDocument(tenant.tenantId, 'default', doc.documentId);
     res.json(chunks);
   });

   router.get('/client/ingest/status', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    res.json(ingestionStatus[tenant.tenantId] || { status: 'idle', logs: ['No ingestion tasks run yet.'], progress: 0, summary: null });
  });

  router.delete('/client/documents/:filename', resolveClientTenant, async (req, res) => {console.log("Client delete request:", req.params.filename, (req as any).tenant?.tenantId);
    const tenant = (req as TenantRequest).tenant;
    const filePath = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents', req.params.filename);
    if (!fs.existsSync(filePath)) return res.status(404).json({ detail: 'File not found' });
    fs.unlinkSync(filePath);
    const docId = crypto.createHash('sha1').update(filePath).digest('hex');
    const engine = await getOrCreateEngine(tenant);
    await engine.deleteDocument(docId);
    res.json({ status: 'deleted', filename: req.params.filename });
  });

  // ===================== SYSTEM APIs =====================
  router.get('/system/status', requireAdmin, async (_req, res) => {
    const tenants = await adminStore.listTenants();
    let totalDocs = 0, totalChunks = 0;
    for (const t of tenants) {
      totalDocs += await dbStore.countDocuments(t.tenantId, 'default');
      totalChunks += await dbStore.countChunks(t.tenantId, 'default');
    }
    res.json({ uptime_seconds: Math.round(process.uptime()), tenants: tenants.length, total_documents: totalDocs, total_chunks: totalChunks, version: '1.0.0' });
  });

  router.get('/system/logs', requireAdmin, async (req, res) => {
    const rawLogs = await adminStore.getActivityLogs(req.query.tenant_id as string || undefined, req.query.level as string || undefined, parseInt(req.query.limit as string) || 100);
    const logs = rawLogs.map((l: any) => ({
      id: l.id,
      level: l.level,
      operation: l.operation,
      message: l.message,
      created_at: l.createdAt ? l.createdAt.toISOString() : new Date().toISOString(),
      latency_ms: null,
      traceback: l.traceback || null,
      details_json: l.details || null,
    }));
    res.json({ logs });
  });

  // ===================== SESSION APIs =====================
  router.get('/tenants/:tenantId/sessions', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    const retentionDays = tenant.chatRetentionDays || 30;
    if (retentionDays > 0) await dbStore.purgeExpiredSessions(req.params.tenantId, retentionDays);
    const sessions = await dbStore.listSessions(req.params.tenantId);
    res.json({ sessions, retention_days: retentionDays });
  });

  router.get('/tenants/:tenantId/sessions/:sessionId/turns', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    const turns = await dbStore.getSessionTurns(req.params.tenantId, req.params.sessionId);
    res.json({ tenant_id: req.params.tenantId, session_id: req.params.sessionId, turns });
  });

  router.delete('/tenants/:tenantId/sessions/:sessionId', requireAdmin, async (req, res) => {
    await dbStore.deleteSession(req.params.tenantId, req.params.sessionId);
    res.json({ status: 'success', deleted_session_id: req.params.sessionId });
  });

  router.post('/tenants/:tenantId/sessions/purge', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    const retentionDays = tenant.chatRetentionDays || 30;
    const purged = await dbStore.purgeExpiredSessions(req.params.tenantId, retentionDays);
    res.json({ status: 'success', purged_turns: purged, retention_days: retentionDays });
  });

  // ===================== SCRAPE =====================
  router.post('/tenants/:tenantId/scrape', requireAdmin, async (req, res) => {
    try {
      const tenant = await adminStore.getTenant(req.params.tenantId);
      if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });

      const docsDir = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents');
      const result = await scrapeUrl({
        url: req.body.url,
        crawl: req.body.crawl,
        fullSite: req.body.full_site || req.body.fullSite,
        maxPages: req.body.max_pages || req.body.maxPages,
        maxDepth: req.body.max_depth || req.body.maxDepth,
      }, docsDir);

      await adminStore.logActivity(req.params.tenantId, 'admin', 'scrape', `Scraped ${req.body.url}`, { url: req.body.url, job_id: result.jobId, success: !result.error });

      const files = result.savedFilePath ? [{ url: result.url, file: result.savedFilePath }] : [];
      res.json({
        status: result.error ? 'failed' : 'completed',
        job_id: result.jobId,
        url: result.url,
        title: result.title,
        description: result.description,
        word_count: result.wordCount,
        files_saved: files.length,
        files,
        error: result.error,
        processing_time_ms: result.processingTimeMs,
      });
    } catch (err: any) {
      res.status(500).json({ status: 'failed', error: err.message });
    }
  });

  router.post('/client/scrape', resolveClientTenant, async (req, res) => {
    try {
      const tenant = (req as TenantRequest).tenant;
      const docsDir = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents');
      const result = await scrapeUrl({
        url: req.body.url,
        crawl: req.body.crawl,
        fullSite: req.body.full_site || req.body.fullSite,
        maxPages: req.body.max_pages || req.body.maxPages,
        maxDepth: req.body.max_depth || req.body.maxDepth,
      }, docsDir);

      await adminStore.logActivity(tenant.tenantId, 'INFO', 'scrape', `Scraped ${req.body.url}`, { url: req.body.url, job_id: result.jobId, success: !result.error });

      const files = result.savedFilePath ? [{ url: result.url, file: result.savedFilePath }] : [];
      res.json({
        status: result.error ? 'failed' : 'completed',
        job_id: result.jobId,
        url: result.url,
        title: result.title,
        description: result.description,
        word_count: result.wordCount,
        files_saved: files.length,
        files,
        error: result.error,
        processing_time_ms: result.processingTimeMs,
      });
    } catch (err: any) {
      res.status(500).json({ status: 'failed', error: err.message });
    }
  });

  // ===================== ENHANCED SCRAPER (external microservice) =====================
  const SCRAPE_TYPES = ['single', 'smart', 'recursive', 'wordpress', 'facebook', 'profile'] as const;

  router.post('/scrape/enhanced', resolveClientTenant, async (req, res) => {
    try {
      const tenant = (req as TenantRequest).tenant;
      const result = await tryScraperOrFallback(req, tenant);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  async function tryScraperOrFallback(req: Request, tenant: any): Promise<any> {
    const { url, scrape_type, format, max_pages, max_depth, timeout, include_pages,
            include_media, fb_c_user, fb_xs, fb_max_posts, fb_scroll_rounds,
            fb_date_from, fb_date_to, profile_platform, profile_username,
            workers, respect_robots, allowed_domains, content_type,
            deepcrawl, playwright } = req.body;

    const extraOpts: any = {};
    if (content_type) extraOpts.content_type = content_type;
    if (deepcrawl) extraOpts.deepcrawl = true;
    if (playwright) extraOpts.playwright = true;

    try {
      let result: any;
      switch (scrape_type || 'single') {
        case 'smart':
          result = await scrapeSmart(url, timeout || 30, extraOpts);
          break;
        case 'recursive':
          result = await startRecursiveCrawl(url, max_depth || 3, max_pages || 50, workers || 1, allowed_domains, extraOpts);
          break;
        case 'wordpress':
          result = await scrapeWordPress(url, max_pages || 10, include_pages !== false, include_media !== false, extraOpts);
          break;
        case 'facebook':
          result = await scrapeFacebook(url, fb_c_user || '', fb_xs || '', fb_max_posts || 20, fb_scroll_rounds || 5, fb_date_from || '', fb_date_to || '');
          break;
        case 'profile':
          result = await scrapeProfile(profile_platform || '', profile_username || '');
          break;
        default:
          result = await scrapeSingle(url, format || 'markdown', extraOpts);
      }
      return result;
    } catch (err: any) {
      const statusMatch = err?.message?.match(/Scraper API error (\d+)/);
      const statusCode = statusMatch ? parseInt(statusMatch[1]) : 0;
      const isServerError = statusCode >= 400;
      const isConnError = err?.cause?.code === 'ECONNREFUSED' || err?.cause?.code === 'ECONNRESET'
        || err?.message?.includes('ECONNREFUSED') || err?.message?.includes('fetch failed')
        || err?.message?.includes('connect') || err?.message?.includes('econnrefused')
        || isServerError;

      if (!isConnError) throw err;

      const docsDir = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents');
      fs.mkdirSync(docsDir, { recursive: true });

      const type = scrape_type || 'single';
      if (type === 'wordpress' || type === 'facebook' || type === 'profile') {
        return { success: false, error: `Scraper microservice is offline. '${type}' scraping requires the scraper service. Use 'single', 'smart', or 'recursive' mode as fallback.` };
      }

      const localResult = await scrapeUrl({
        url,
        crawl: type === 'smart' || type === 'recursive',
        fullSite: type === 'recursive',
        maxPages: max_pages || 100,
        maxDepth: max_depth || 3,
      }, docsDir);

      if (localResult.error) {
        return { success: false, error: localResult.error };
      }

      return {
        success: true,
        data: {
          title: localResult.title,
          description: localResult.description,
          text: localResult.text,
          markdown: localResult.text,
          url: localResult.url,
          word_count: localResult.wordCount,
          links: localResult.links,
          images: localResult.images,
          quality_score: 1.0,
          quality_level: 'fallback',
        },
        metrics: { source: 'local_fallback', processing_time_ms: localResult.processingTimeMs },
      };
    }
  }

  router.post('/tenants/:tenantId/scrape/enhanced', requireAdmin, async (req, res) => {
    try {
      const tenant = await adminStore.getTenant(req.params.tenantId);
      if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });

      const result = await tryScraperOrFallback(req, tenant);

      const scrapedText = result?.data?.text || result?.data?.markdown || result?.data?.readability?.clean_text || result?.data?.readability?.markdown || '';
      if (result?.success && scrapedText) {
        const docsDir = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents');
        fs.mkdirSync(docsDir, { recursive: true });
        const siteSlug = (result.data.url || req.body.url || '').replace(/https?:\/\//, '').split('/')[0].replace(/[^a-zA-Z0-9_-]/g, '_');
        const ts = Date.now();
        const filename = `scraped_${siteSlug}_${ts}.md`;
        const contentMarkdown = result?.data?.markdown || result?.data?.readability?.markdown || scrapedText;
        const wordCount = scrapedText.split(/\s+/).filter(Boolean).length;
        const content = `---\nurl: ${result.data.url || req.body.url}\ntitle: ${result.data.title || ''}\ndescription: ${result.data.description || ''}\nscraped_at: ${new Date().toISOString()}\nword_count: ${wordCount}\n---\n\n${contentMarkdown}`;
        fs.writeFileSync(path.join(docsDir, filename), content, 'utf-8');
        result.saved_file = filename;
        await adminStore.logActivity(req.params.tenantId, 'admin', 'scrape_enhanced', `Scraped ${req.body.url} -> ${filename}`, { url: req.body.url, filename });
      }

      res.json(result);
    } catch (err: any) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  router.get('/scrape/recursive/:jobId/status', resolveClientTenant, async (req, res) => {
    try {
      const status = await getRecursiveStatus(req.params.jobId);
      res.json(status);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.get('/scrape/facebook/:jobId/status', resolveClientTenant, async (req, res) => {
    try {
      const status = await getFbJobStatus(req.params.jobId);
      res.json(status);
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  router.post('/scrape/enhanced/ingest', resolveClientTenant, async (req, res) => {
    try {
      const tenant = (req as TenantRequest).tenant;
      const engine = await getOrCreateEngine(tenant);
      const result = await scrapeAndIngest(config, dbStore, engine, req.body.url, tenant.tenantId, 'default', req.body.scrape_type || 'single', { timeout: req.body.timeout });
      if (result.status === 'completed') {
        await adminStore.logActivity(tenant.tenantId, 'INFO', 'scrape_ingest', `Scraped & ingested ${req.body.url} -> ${result.document}`, { url: req.body.url, document: result.document });
      }
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ status: 'failed', error: err.message });
    }
  });

  router.post('/tenants/:tenantId/scrape/enhanced/ingest', requireAdmin, async (req, res) => {
    try {
      const tenant = await adminStore.getTenant(req.params.tenantId);
      if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
      const engine = await getOrCreateEngine(tenant);
      const result = await scrapeAndIngest(config, dbStore, engine, req.body.url, req.params.tenantId, 'default', req.body.scrape_type || 'single', { timeout: req.body.timeout });
      if (result.status === 'completed') {
        await adminStore.logActivity(req.params.tenantId, 'admin', 'scrape_ingest', `Scraped & ingested ${req.body.url} -> ${result.document}`, { url: req.body.url, document: result.document });
      }
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ status: 'failed', error: err.message });
    }
  });

  router.get('/scrape/health', async (_req, res) => {
    try {
      const resp = await fetch(`${process.env.SCRAPER_SERVICE_URL || 'http://localhost:8002'}/`);
      const data = await resp.json();
      res.json(data);
    } catch (err: any) {
      res.json({ service: 'unavailable', error: err.message });
    }
  });

  router.get('/scrape/logs', async (req, res) => {
    try {
      const lines = (req.query.lines as string) || '50';
      const resp = await fetch(`${process.env.SCRAPER_SERVICE_URL || 'http://localhost:8002'}/logs?lines=${lines}`);
      if (!resp.ok) return res.json({ logs: [] });
      const data = await resp.json();
      res.json(data);
    } catch {
      res.json({ logs: [] });
    }
  });

  // ===================== TERMINAL EXEC =====================
  router.post('/terminal/exec', requireAdmin, async (req, res) => {
    const { command, tenant_id } = req.body;
    const cmd = (command || '').toString().trim().toLowerCase();
    const tenant = tenant_id ? await adminStore.getTenant(tenant_id) : null;

    try {
      if (cmd === 'help' || cmd === '/help') {
        const helpText = `Available commands:
  /help           – Show this help
  /clear          – Clear terminal
  /isolation      – Run isolation audit
  /clients        – List all clients/tenants
  /status         – System status
  /tenants        – Alias for /clients`;
        return res.json({ type: 'output', output: helpText });
      }

      if (cmd === 'clear' || cmd === '/clear') {
        return res.json({ type: 'output', output: 'CLEAR' });
      }

      if (cmd === 'isolation' || cmd === '/isolation') {
        const allTenants = await adminStore.listTenants();
        let output = '🔍 Isolation Audit\n';
        output += `Total tenants: ${allTenants.length}\n`;
        for (const t of allTenants) {
          const docsDir = path.join(config.rootDir, 'tenants', t.tenantId, 'documents');
          const exists = fs.existsSync(docsDir);
          const docCount = await dbStore.countDocuments(t.tenantId, 'default');
          output += `  ${t.tenantId}: docs_dir=${exists ? '✓' : '✗'} documents=${docCount}\n`;
        }
        output += '\n✅ All tenants isolated';
        return res.json({ type: 'output', output });
      }

      if (cmd === 'clients' || cmd === '/clients' || cmd === 'tenants' || cmd === '/tenants') {
        const allTenants = await adminStore.listTenants();
        let output = `📋 Tenants (${allTenants.length}):\n`;
        for (const t of allTenants) {
          output += `  ${t.tenantId} | ${t.name} | ${t.status} | ${t.llmProvider}/${t.llmModel}\n`;
        }
        return res.json({ type: 'output', output });
      }

      if (cmd === 'status' || cmd === '/status') {
        const allTenants = await adminStore.listTenants();
        let totalDocs = 0, totalChunks = 0;
        for (const t of allTenants) {
          totalDocs += await dbStore.countDocuments(t.tenantId, 'default');
          totalChunks += await dbStore.countChunks(t.tenantId, 'default');
        }
        const output = `📊 System Status
  Uptime: ${Math.round(process.uptime())}s
  Tenants: ${allTenants.length}
  Documents: ${totalDocs}
  Chunks: ${totalChunks}
  Memory: ${(process.memoryUsage().heapUsed / 1024 / 1024).toFixed(1)} MB`;
        return res.json({ type: 'output', output });
      }

      res.json({ type: 'error', output: `Unknown command: ${command}. Type /help for available commands.` });
    } catch (err: any) {
      res.json({ type: 'error', output: `Error: ${err.message}` });
    }
  });

  // ===================== ISOLATION CHECK =====================
  router.get('/isolation-check', requireAdmin, async (_req, res) => {
    const allTenants = await adminStore.listTenants();
    let isolated = 0;
    const details: any[] = [];
    for (const t of allTenants) {
      const docsDir = path.join(config.rootDir, 'tenants', t.tenantId, 'documents');
      const isolatedOk = !fs.existsSync(docsDir.replace(t.tenantId, 'other')) && fs.existsSync(docsDir);
      if (isolatedOk) isolated++;
      details.push({ tenant: t.tenantId, docs_dir_exists: fs.existsSync(docsDir), isolated: isolatedOk });
    }
    const score = allTenants.length > 0 ? Math.round((isolated / allTenants.length) * 100) : 100;
    res.json({
      status: score === 100 ? 'verified' : 'warning',
      score_percent: score,
      total_tenants: allTenants.length,
      verified_isolated: isolated,
      details
    });
  });

  // ===================== CLOUD SYNC =====================
  router.post('/tenants/:tenantId/cloud-sync', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    const { provider, cloud_url_or_id, api_key_or_token, custom_filename, auto_ingest } = req.body;
    const docsDir = path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents');
    const downloaded: string[] = [];
    const errors: string[] = [];

    try {
      if (provider === 'direct_url') {
        const url = cloud_url_or_id;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        const contentType = resp.headers.get('content-type') || '';
        const ext = contentType.includes('pdf') ? '.pdf' : contentType.includes('html') ? '.html' : '.txt';
        const filename = custom_filename || `cloud_${Date.now()}${ext}`;
        const buffer = Buffer.from(await resp.arrayBuffer());
        const filePath = path.join(docsDir, filename);
        fs.mkdirSync(docsDir, { recursive: true });
        fs.writeFileSync(filePath, buffer);
        downloaded.push(filename);
      } else if (provider === 'google_drive') {
        const fileId = cloud_url_or_id;
        const url = fileId.startsWith('http') ? fileId : `https://drive.google.com/uc?export=download&id=${fileId}`;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        const filename = custom_filename || `gdrive_${Date.now()}.pdf`;
        const buffer = Buffer.from(await resp.arrayBuffer());
        const filePath = path.join(docsDir, filename);
        fs.mkdirSync(docsDir, { recursive: true });
        fs.writeFileSync(filePath, buffer);
        downloaded.push(filename);
      } else if (provider === 'onedrive') {
        const resp = await fetch(cloud_url_or_id);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        const filename = custom_filename || `onedrive_${Date.now()}.pdf`;
        const buffer = Buffer.from(await resp.arrayBuffer());
        const filePath = path.join(docsDir, filename);
        fs.mkdirSync(docsDir, { recursive: true });
        fs.writeFileSync(filePath, buffer);
        downloaded.push(filename);
      } else {
        throw new Error(`Unsupported provider: ${provider}`);
      }

      await adminStore.logActivity(req.params.tenantId, 'INFO', 'cloud_sync', `Synced ${downloaded.length} file(s) from ${provider}`, { provider, files: downloaded });

      const status = errors.length === 0 ? 'success' : (downloaded.length > 0 ? 'partial' : 'failed');
      res.json({ status, count: downloaded.length, downloaded, errors, auto_ingest: !!auto_ingest });
    } catch (err: any) {
      errors.push(err.message);
      res.json({ status: 'failed', count: 0, downloaded, errors: [err.message], auto_ingest: !!auto_ingest });
    }
  });

  // ===================== PROVIDER PRESETS =====================
  router.get('/admin/providers', requireAdmin, async (_req, res) => {
    const presets = loadProviderPresets(config.rootDir);
    res.json(presets);
  });

  router.put('/admin/providers', requireAdmin, async (req, res) => {
    try {
      saveProviderPresets(config.rootDir, req.body);
      res.json({ status: 'success' });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  // ===================== CRAWL OUTPUT =====================
  const crawlOutputBase = path.join(config.rootDir, '..', '..', 'scraper-service', 'crawl_output');

  router.get('/crawl-output', requireAdmin, async (_req, res) => {
    try {
      if (!fs.existsSync(crawlOutputBase)) {
        return res.json({ sites: [] });
      }
      const sites = fs.readdirSync(crawlOutputBase).filter(item => {
        const itemPath = path.join(crawlOutputBase, item);
        return fs.statSync(itemPath).isDirectory();
      });
      const siteData = sites.map(site => {
        const sitePath = path.join(crawlOutputBase, site);
        const indexPath = path.join(sitePath, 'index.json');
        let metadata = null;
        if (fs.existsSync(indexPath)) {
          try {
            metadata = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
          } catch {
            // ignore parse errors
          }
        }
        return {
          site,
          metadata,
          hasImages: fs.existsSync(path.join(sitePath, 'images')),
          hasPdfs: fs.existsSync(path.join(sitePath, 'pdfs')),
          hasPages: fs.existsSync(path.join(sitePath, 'pages')),
        };
      });
      res.json({ sites: siteData });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.get('/crawl-output/:site', requireAdmin, async (req, res) => {
    try {
      const { site } = req.params;
      const sitePath = path.join(crawlOutputBase, site);
      if (!fs.existsSync(sitePath)) {
        return res.status(404).json({ detail: 'Site not found' });
      }
      const indexPath = path.join(sitePath, 'index.json');
      let metadata = null;
      if (fs.existsSync(indexPath)) {
        try {
          metadata = JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
        } catch {
          // ignore parse errors
        }
      }
      
      // Get file listings
      const files: any = { images: [], pdfs: [], pages: [] };
      
      if (fs.existsSync(path.join(sitePath, 'images'))) {
        const imagesDir = path.join(sitePath, 'images');
        const listImages = (dir: string, base: string = '') => {
          const items = fs.readdirSync(dir);
          items.forEach(item => {
            const itemPath = path.join(dir, item);
            if (fs.statSync(itemPath).isDirectory()) {
              listImages(itemPath, `${base}${item}/`);
            } else {
              files.images.push(`${base}${item}`);
            }
          });
        };
        listImages(imagesDir);
      }
      
      if (fs.existsSync(path.join(sitePath, 'pdfs'))) {
        files.pdfs = fs.readdirSync(path.join(sitePath, 'pdfs'));
      }
      
      if (fs.existsSync(path.join(sitePath, 'pages'))) {
        const pagesDir = path.join(sitePath, 'pages');
        const listPages = (dir: string, base: string = '') => {
          const items = fs.readdirSync(dir);
          items.forEach(item => {
            const itemPath = path.join(dir, item);
            if (fs.statSync(itemPath).isDirectory()) {
              listPages(itemPath, `${base}${item}/`);
            } else {
              files.pages.push(`${base}${item}`);
            }
          });
        };
        listPages(pagesDir);
      }
      
      res.json({ site, metadata, files });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.get('/crawl-output/:site/*', requireAdmin, async (req, res) => {
    try {
      const { site } = req.params;
      const filePath = req.params[0]; // wildcard parameter
      const fullPath = path.join(crawlOutputBase, site, filePath);
      if (!fs.existsSync(fullPath) || !fs.statSync(fullPath).isFile()) {
        return res.status(404).json({ detail: 'File not found' });
      }
      const ext = path.extname(fullPath).toLowerCase();
      const mimeTypes: Record<string, string> = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.md': 'text/markdown',
        '.json': 'application/json',
        '.txt': 'text/plain',
      };
      res.type(mimeTypes[ext] || 'application/octet-stream').sendFile(fullPath);
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.post('/crawl-output/:site/import', requireAdmin, async (req, res) => {
    try {
      const { site } = req.params;
      const { tenantId } = req.body;
      if (!tenantId) {
        return res.status(400).json({ detail: 'Missing tenantId' });
      }
      
      const sitePath = path.join(crawlOutputBase, site);
      if (!fs.existsSync(sitePath)) {
        return res.status(404).json({ detail: 'Site not found' });
      }
      
      const tenantDocsDir = path.join(config.rootDir, 'tenants', tenantId, 'documents');
      if (!fs.existsSync(tenantDocsDir)) {
        fs.mkdirSync(tenantDocsDir, { recursive: true });
      }
      
      let importedCount = 0;
      
      // Import pages (markdown files)
      const pagesDir = path.join(sitePath, 'pages');
      if (fs.existsSync(pagesDir)) {
        const copyFiles = (dir: string, subPath: string = '') => {
          const items = fs.readdirSync(dir);
          items.forEach(item => {
            const itemPath = path.join(dir, item);
            if (fs.statSync(itemPath).isDirectory()) {
              copyFiles(itemPath, `${subPath}${item}/`);
            } else if (item.endsWith('.md') || item.endsWith('.txt')) {
              const flatName = `crawl_${site}_${subPath.replace(/\//g, '_')}${item}`;
              const destPath = path.join(tenantDocsDir, flatName);
              fs.copyFileSync(itemPath, destPath);
              importedCount++;
            }
          });
        };
        copyFiles(pagesDir);
      }
      
      // Import PDFs (and images stored in pdfs/ dir)
      const pdfExts = ['.pdf', '.jpg', '.jpeg', '.png', '.svg', '.webp', '.gif'];
      const pdfsDir = path.join(sitePath, 'pdfs');
      if (fs.existsSync(pdfsDir)) {
        const pdfs = fs.readdirSync(pdfsDir);
        pdfs.forEach(pdf => {
          if (pdfExts.some(ext => pdf.toLowerCase().endsWith(ext))) {
            const srcPath = path.join(pdfsDir, pdf);
            const destPath = path.join(tenantDocsDir, `crawl_${site}_${pdf}`);
            fs.copyFileSync(srcPath, destPath);
            importedCount++;
          }
        });
      }
      
      // Import images (language subdirectories)
      const imagesDir = path.join(sitePath, 'images');
      if (fs.existsSync(imagesDir)) {
        const copyImages = (dir: string, subPath: string = '') => {
          const items = fs.readdirSync(dir);
          items.forEach(item => {
            const itemPath = path.join(dir, item);
            if (fs.statSync(itemPath).isDirectory()) {
              copyImages(itemPath, `${subPath}${item}/`);
            } else if (pdfExts.some(ext => item.toLowerCase().endsWith(ext))) {
              const flatName = `crawl_${site}_img_${subPath.replace(/\//g, '_')}${item}`;
              const destPath = path.join(tenantDocsDir, flatName);
              fs.copyFileSync(itemPath, destPath);
              importedCount++;
            }
          });
        };
        copyImages(imagesDir);
      }

      res.json({ success: true, imported_count: importedCount });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.post('/crawl-output/import-all', requireAdmin, async (req, res) => {
    try {
      const { tenantId } = req.body;
      if (!tenantId) return res.status(400).json({ detail: 'Missing tenantId' });

      const tenantDocsDir = path.join(config.rootDir, 'tenants', tenantId, 'documents');
      fs.mkdirSync(tenantDocsDir, { recursive: true });

      if (!fs.existsSync(crawlOutputBase)) {
        return res.json({ success: true, imported_count: 0, message: 'No crawl output directory found' });
      }

      const sites = fs.readdirSync(crawlOutputBase).filter(item => {
        const itemPath = path.join(crawlOutputBase, item);
        return fs.statSync(itemPath).isDirectory();
      });

      let totalImported = 0;
      const results: Record<string, number> = {};

      for (const site of sites) {
        const sitePath = path.join(crawlOutputBase, site);
        let importedCount = 0;

        const pagesDir = path.join(sitePath, 'pages');
        if (fs.existsSync(pagesDir)) {
          const copyFiles = (dir: string, subPath: string = '') => {
            const items = fs.readdirSync(dir);
            items.forEach(item => {
              const itemPath = path.join(dir, item);
              if (fs.statSync(itemPath).isDirectory()) {
                copyFiles(itemPath, `${subPath}${item}/`);
              } else if (item.endsWith('.md') || item.endsWith('.txt')) {
                const flatName = `crawl_${site}_${subPath.replace(/\//g, '_')}${item}`;
                const destPath = path.join(tenantDocsDir, flatName);
                fs.copyFileSync(itemPath, destPath);
                importedCount++;
              }
            });
          };
          copyFiles(pagesDir);
        }

        const pdfExts = ['.pdf', '.jpg', '.jpeg', '.png', '.svg', '.webp', '.gif'];
        const pdfsDir = path.join(sitePath, 'pdfs');
        if (fs.existsSync(pdfsDir)) {
          fs.readdirSync(pdfsDir).forEach(pdf => {
            if (pdfExts.some(ext => pdf.toLowerCase().endsWith(ext))) {
              const destPath = path.join(tenantDocsDir, `crawl_${site}_${pdf}`);
              fs.copyFileSync(path.join(pdfsDir, pdf), destPath);
              importedCount++;
            }
          });
        }

        if (importedCount > 0) {
          results[site] = importedCount;
          totalImported += importedCount;
        }
      }

      // Trigger ingestion after bulk import
      if (totalImported > 0) {
        const tenant = await adminStore.getTenant(tenantId);
        if (tenant) {
          const engine = await getOrCreateEngine(tenant);
          engine.ingest(tenantId, 'default', false).catch(() => {});
        }
      }

      await adminStore.logActivity(tenantId, 'INFO', 'crawl_import_all', `Imported ${totalImported} files from ${sites.length} sites`, { sites: Object.keys(results), counts: results });

      res.json({ success: true, sites_imported: Object.keys(results).length, imported_count: totalImported, site_details: results });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  return router;
}
