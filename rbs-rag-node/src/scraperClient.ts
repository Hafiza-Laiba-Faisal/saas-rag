/**
 * Scraper Service Client — bridges Node.js RAG engine with the enhanced scraper microservice.
 * Calls the scraper service REST API, saves scraped content with rich metadata,
 * and feeds into the RAG ingestion pipeline.
 */

import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { v4 as uuidv4 } from 'uuid';
import { AppConfig } from './config.js';
import { RagEngine } from './engine.js';
import { DbStore } from './store.js';
import { LoadedDocument } from './types/models.js';

const SCRAPER_BASE_URL = process.env.SCRAPER_SERVICE_URL || 'http://localhost:8002';
const SCRAPER_API_KEY = process.env.SCRAPER_API_KEY || '';
const DEEPCRAWL_API_KEY = process.env.DEEPCRAWL_API_KEY || '';

interface ScraperResult {
  status: 'completed' | 'failed';
  document?: string;
  title?: string;
  word_count?: number;
  chunks?: number;
  metadata?: Record<string, any>;
  error?: any;
}

interface ScraperApiResponse {
  success: boolean;
  data?: any;
  errors?: any[];
  metrics?: Record<string, any>;
}

export async function callScraper(endpoint: string, payload: any): Promise<ScraperApiResponse> {
  const url = `${SCRAPER_BASE_URL}${endpoint}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (SCRAPER_API_KEY) headers['X-API-Key'] = SCRAPER_API_KEY;
  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Scraper API error ${response.status}: ${errText}`);
  }
  const result = await response.json() as ScraperApiResponse;
  if (result.success === false) {
    const errMsg = result.errors ? (Array.isArray(result.errors) ? result.errors.join('; ') : JSON.stringify(result.errors)) : 'Scraper returned success=false';
    throw new Error(errMsg);
  }
  return result;
}

export async function scrapeSingle(
  url: string,
  format: 'json' | 'markdown' = 'markdown',
  extraOpts: Record<string, any> = {}
): Promise<ScraperApiResponse> {
  return callScraper('/crawl', { url, format, ...extraOpts });
}

export async function scrapeSmart(
  url: string,
  timeout = 30,
  extraOpts: Record<string, any> = {}
): Promise<ScraperApiResponse> {
  const payload: any = { url, timeout, ...extraOpts };
  if (DEEPCRAWL_API_KEY && !extraOpts.deepcrawl) payload.deepcrawl_api_key = DEEPCRAWL_API_KEY;
  return callScraper('/crawl/smart', payload);
}

export async function startRecursiveCrawl(
  url: string,
  maxDepth = 2,
  maxPages = 50,
  workers = 1,
  allowedDomains?: string[],
  extraOpts: Record<string, any> = {}
): Promise<ScraperApiResponse> {
  return callScraper('/crawl/recursive', {
    url, max_depth: maxDepth, max_pages: maxPages,
    workers, allowed_domains: allowedDomains || null,
    respect_robots: true,
    ...extraOpts,
  });
}

export async function getRecursiveStatus(jobId: string): Promise<any> {
  const resp = await fetch(`${SCRAPER_BASE_URL}/crawl/recursive/status/${jobId}`, {
    signal: AbortSignal.timeout(30000),
  });
  if (!resp.ok) throw new Error(`Status fetch failed: ${resp.status}`);
  return resp.json();
}

export async function scrapeWordPress(
  url: string,
  maxPages = 10,
  includePages = true,
  includeMedia = true,
  extraOpts: Record<string, any> = {}
): Promise<ScraperApiResponse> {
  return callScraper('/scrape/wordpress', {
    url, max_pages: maxPages, include_pages: includePages, include_media: includeMedia,
    ...extraOpts,
  });
}

export async function scrapeAndIngest(
  config: AppConfig,
  store: DbStore,
  engine: RagEngine,
  url: string,
  tenantId: string,
  knowledgeBaseId = 'default',
  scrapeType: 'single' | 'smart' = 'single',
  options?: { timeout?: number }
): Promise<ScraperResult> {
  let apiResult: ScraperApiResponse;

  if (scrapeType === 'smart') {
    apiResult = await scrapeSmart(url, options?.timeout || 30);
  } else {
    apiResult = await scrapeSingle(url, 'markdown');
  }

  if (!apiResult.success) {
    return { status: 'failed', error: apiResult.errors };
  }

  const data = apiResult.data || {};
  const title = data.title || url;
  const text = data.markdown || data.json?.markdown || data.text || '';
  const description = data.description || '';

  if (!text.trim()) {
    return { status: 'failed', error: 'No text extracted from URL' };
  }

  const scrapedMeta: Record<string, any> = {
    source_url: url,
    title,
    description,
    scrape_type: scrapeType,
    scraped_at: new Date().toISOString(),
    word_count: text.split(/\s+/).filter(Boolean).length,
    content_type: 'web_scrape',
  };
  if (data.quality_score != null) {
    scrapedMeta.quality_score = data.quality_score;
    scrapedMeta.quality_level = data.quality_level || 'unknown';
  }

  const tenantDir = path.join(config.rootDir, 'tenants', tenantId, 'documents');
  fs.mkdirSync(tenantDir, { recursive: true });

  const siteSlug = url.replace(/https?:\/\//, '').split('/')[0];
  const safeTitle = title.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 60);
  const filename = `scraped_${siteSlug}_${safeTitle}_${uuidv4().slice(0, 8)}.md`;
  const filePath = path.join(tenantDir, filename);

  const fileContent = `---
url: ${url}
title: ${title}
description: ${description}
scrape_type: ${scrapeType}
scraped_at: ${scrapedMeta.scraped_at}
word_count: ${scrapedMeta.word_count}
---

${text}
`;
  fs.writeFileSync(filePath, fileContent, 'utf-8');

  const docId = crypto.createHash('sha1').update(filePath).digest('hex');
  const doc: LoadedDocument = {
    documentId: docId,
    path: filePath,
    name: filename,
    documentType: 'md',
    text,
    metadata: scrapedMeta,
    ocrApplied: false,
    ocrEngine: null,
    pageCount: null,
  };

  const chunks = engine.chunker.chunk(doc, tenantId, knowledgeBaseId);
  const embeddings = await engine.embeddingProvider.embed(chunks.map(c => c.text));
  for (let i = 0; i < chunks.length; i++) {
    chunks[i].embedding = embeddings[i];
  }

  await store.upsertDocument(doc, tenantId, knowledgeBaseId, 'scrape', url);
  await store.upsertChunks(chunks);

  if (engine.vectorStore?.initialized) {
    try {
      await engine.vectorStore.upsertChunks('rag_chunks', chunks);
    } catch { /* degrade gracefully */ }
  }

  return {
    status: 'completed',
    document: filename,
    title,
    word_count: text.split(/\s+/).filter(Boolean).length,
    chunks: chunks.length,
    metadata: scrapedMeta,
  };
}
