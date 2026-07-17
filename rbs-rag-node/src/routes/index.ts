import { Router, Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import crypto from 'crypto';
import jwt from 'jsonwebtoken';
import { AppConfig } from '../config.js';
import { AdminStore } from '../adminStore.js';
import { DbStore } from '../store.js';
import { RagEngine, createEngineFromTenant } from '../engine.js';

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
      res.json({ status: 'success', token, token_type: 'Bearer' });
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
      tenant_id: t.tenantId,
      name: t.name,
      api_key: '***',
      status: t.status,
      subscription_tier: t.subscriptionTier,
      monthly_fee: t.monthlyFee,
      llm_provider: t.llmProvider,
      llm_model: t.llmModel,
      llm_api_key: '***',
      embedding_provider: t.embeddingProvider,
      embedding_model: t.embeddingModel,
      embedding_dimensions: t.embeddingDimensions,
      embedding_api_key: t.embeddingApiKey ? '***' : null,
      retrieval_top_k: t.retrievalTopK,
      retrieval_rerank_top_k: t.retrievalRerankTopK,
      retrieval_final_context_k: t.retrievalFinalContextK,
      retrieval_dense_weight: t.retrievalDenseWeight,
      retrieval_sparse_weight: t.retrievalSparseWeight,
      chunking_max_tokens: t.chunkingMaxTokens,
      chunking_overlap_tokens: t.chunkingOverlapTokens,
      chunking_semantic: t.chunkingSemantic,
      chunking_semantic_threshold: t.chunkingSemanticThreshold,
      reranker_type: t.rerankerType,
      session_memory_limit: t.sessionMemoryLimit,
      chat_retention_days: t.chatRetentionDays,
      system_prompt: t.systemPrompt,
      doc_count: await dbStore.countDocuments(t.tenantId, 'default'),
      chunk_count: await dbStore.countChunks(t.tenantId, 'default'),
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
      res.json({ status: 'success', tenant_id: tid, api_key: apiKey });
    } catch (err: any) {
      res.status(500).json({ detail: err.message });
    }
  });

  router.get('/tenants/:tenantId', requireAdmin, async (req, res) => {
    const t = await adminStore.getTenant(req.params.tenantId);
    if (!t) return res.status(404).json({ detail: 'Tenant not found' });
    res.json({
      tenant_id: t.tenantId, name: t.name, api_key: '***', status: t.status,
      subscription_tier: t.subscriptionTier, monthly_fee: t.monthlyFee,
      llm_provider: t.llmProvider, llm_model: t.llmModel, llm_api_key: '***',
      llm_base_url: t.llmBaseUrl,
      embedding_provider: t.embeddingProvider, embedding_model: t.embeddingModel,
      embedding_dimensions: t.embeddingDimensions, embedding_base_url: t.embeddingBaseUrl,
      embedding_api_key: t.embeddingApiKey ? '***' : null,
      retrieval_top_k: t.retrievalTopK, retrieval_rerank_top_k: t.retrievalRerankTopK,
      retrieval_final_context_k: t.retrievalFinalContextK,
      retrieval_dense_weight: t.retrievalDenseWeight, retrieval_sparse_weight: t.retrievalSparseWeight,
      chunking_max_tokens: t.chunkingMaxTokens, chunking_overlap_tokens: t.chunkingOverlapTokens,
      chunking_semantic: t.chunkingSemantic, chunking_semantic_threshold: t.chunkingSemanticThreshold,
      reranker_type: t.rerankerType, session_memory_limit: t.sessionMemoryLimit,
      chat_retention_days: t.chatRetentionDays, system_prompt: t.systemPrompt,
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
    const result = files.map(name => {
      const filePath = path.join(docsDir, name);
      const stat = fs.statSync(filePath);
      const docId = crypto.createHash('sha1').update(filePath).digest('hex');
      const ingested = ingestedMap[docId];
      return {
        name, size_bytes: stat.size, ingested: !!ingested,
        chunks: 0, extension: path.extname(name).replace('.', ''),
        source: ingested?.source || 'upload',
      };
    });
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
    const allChunks = await dbStore.listChunks(req.params.tenantId, 'default');
    const docChunks = allChunks.filter((c: any) => c.documentId === doc.documentId);
    res.json(docChunks.map(c => ({ chunk_id: c.chunkId, ordinal: c.ordinal, text: c.text, metadata: c.metadata })));
  });

  router.post('/tenants/:tenantId/documents', requireAdmin, async (req, res) => {
    const { default: multer } = await import('multer');
    const upload = multer({ dest: path.join(config.rootDir, 'tenants', req.params.tenantId, 'documents') });
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
    await dbStore.deleteDocument(docId);
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
      res.status(500).json({ detail: `Model API Error: ${err.message}` });
    }
  });

  router.post('/tenants/:tenantId/chat/stream', requireAdmin, async (req, res) => {
    const tenant = await adminStore.getTenant(req.params.tenantId);
    if (!tenant) return res.status(404).json({ detail: 'Tenant not found' });
    if (tenant.status !== 'active') return res.status(403).json({ detail: 'Tenant account is suspended' });
    const { query, session_id, user_id, filters, system_prompt } = req.body;
    const engine = await getOrCreateEngine(tenant);
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    const stream = engine.askStream(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
    for await (const chunk of stream) {
      const data: any = { text: chunk.text, done: chunk.done };
      if (chunk.error) data.error = chunk.error;
      if (chunk.citations) data.citations = chunk.citations.map(c => ({ index: c.index, document_name: c.documentName, section: c.section, chunk_id: c.chunkId }));
      res.write(`data: ${JSON.stringify(data)}\n\n`);
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
    const stream = engine.askStream(query, 'default', session_id || 'default', user_id || 'web-user', filters || null, system_prompt || null);
    for await (const chunk of stream) {
      const data: any = { text: chunk.text, done: chunk.done };
      if (chunk.error) data.error = chunk.error;
      res.write(`data: ${JSON.stringify(data)}\n\n`);
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
    const result = files.map(name => {
      const filePath = path.join(docsDir, name);
      const stat = fs.statSync(filePath);
      const docId = crypto.createHash('sha1').update(filePath).digest('hex');
      const ingested = ingestedMap[docId];
      return { name, size_bytes: stat.size, ingested: !!ingested, chunks: 0, extension: path.extname(name).replace('.', '') };
    });
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
    const upload = multer({ dest: path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents') });
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

  router.get('/client/ingest/status', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    res.json(ingestionStatus[tenant.tenantId] || { status: 'idle', logs: ['No ingestion tasks run yet.'], progress: 0, summary: null });
  });

  router.delete('/client/documents/:filename', resolveClientTenant, async (req, res) => {
    const tenant = (req as TenantRequest).tenant;
    const filePath = path.join(config.rootDir, 'tenants', tenant.tenantId, 'documents', req.params.filename);
    if (!fs.existsSync(filePath)) return res.status(404).json({ detail: 'File not found' });
    fs.unlinkSync(filePath);
    const docId = crypto.createHash('sha1').update(filePath).digest('hex');
    await dbStore.deleteDocument(docId);
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
    const logs = await adminStore.getActivityLogs(req.query.tenant_id as string || undefined, req.query.level as string || undefined, parseInt(req.query.limit as string) || 100);
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

  // ===================== PLACEHOLDER ENDPOINTS =====================
  router.post('/tenants/:tenantId/scrape', requireAdmin, async (req, res) => {
    res.json({ status: 'completed', job_id: 'placeholder', url: req.body.url, files_saved: 0, files: [], error: null, processing_time_ms: 0 });
  });

  router.post('/client/scrape', resolveClientTenant, async (req, res) => {
    res.json({ status: 'completed', job_id: 'placeholder', url: req.body.url, files_saved: 0, files: [], error: null, processing_time_ms: 0 });
  });

  return router;
}
