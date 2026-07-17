import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { LoadedDocument } from './types/models.js';
import { ocrFile, isImageFile } from './ocrClient.js';

const SUPPORTED_EXTENSIONS = new Set([
  '.txt', '.md', '.markdown', '.html', '.htm',
  '.pdf', '.csv', '.json', '.xml',
  '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp',
  '.docx', '.xlsx', '.xls',
]);

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp']);

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

export async function loadDocument(
  filePath: string,
  metadata?: Record<string, any>,
  applyOcr = false,
  ocrServiceUrl?: string,
  ocrApiKey?: string
): Promise<LoadedDocument> {
  const ext = path.extname(filePath).toLowerCase();
  let text = '';
  let ocrApplied = false;
  let ocrEngine: string | null = null;

  if (ext === '.txt' || ext === '.md' || ext === '.markdown') {
    text = fs.readFileSync(filePath, 'utf-8');
  } else if (ext === '.html' || ext === '.htm') {
    text = stripHtml(fs.readFileSync(filePath, 'utf-8'));
  } else if (ext === '.csv') {
    text = fs.readFileSync(filePath, 'utf-8');
  } else if (ext === '.docx') {
    const mammoth = (await import('mammoth')).default;
    const result = await mammoth.extractRawText({ path: filePath });
    text = result.value;
  } else if (ext === '.xlsx' || ext === '.xls') {
    const xlsx = (await import('xlsx')).default;
    const workbook = xlsx.readFile(filePath);
    const sheetNames = workbook.SheetNames;
    for (const name of sheetNames) {
      const sheet = workbook.Sheets[name];
      text += xlsx.utils.sheet_to_csv(sheet) + '\n\n';
    }
  } else if (ext === '.pdf') {
    text = await readPdf(filePath, applyOcr, ocrServiceUrl, ocrApiKey);
    if (text.includes('[OCR]')) {
      ocrApplied = true;
      ocrEngine = 'ocr-service';
    }
  } else if (IMAGE_EXTENSIONS.has(ext)) {
    if (applyOcr && ocrServiceUrl && ocrApiKey) {
      const result = await ocrFile(filePath, ocrServiceUrl, ocrApiKey);
      if (result.text) {
        text = result.text;
        ocrApplied = true;
        ocrEngine = result.ocrEngine;
      }
    }
    if (!text) {
      text = `[Image: ${path.basename(filePath)}]`;
    }
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
    ocrApplied,
    ocrEngine,
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

async function readPdf(filePath: string, applyOcr: boolean, ocrServiceUrl?: string, ocrApiKey?: string): Promise<string> {
  try {
    const dataBuffer = fs.readFileSync(filePath);

    // Try pdf-parse first
    try {
      const pdfParse = (await import('pdf-parse')).default;
      const data = await pdfParse(dataBuffer);
      const extractedText = data.text?.trim() || '';

      if (extractedText.length > 50) {
        return extractedText;
      }
    } catch {}

    // If pdf-parse failed or extracted too little text, try OCR
    if (applyOcr && ocrServiceUrl && ocrApiKey) {
      const result = await ocrFile(filePath, ocrServiceUrl, ocrApiKey);
      if (result.text) {
        return `[OCR] ${result.text}`;
      }
    }

    return `[PDF: ${path.basename(filePath)}]`;
  } catch {
    return `[Error reading PDF: ${path.basename(filePath)}]`;
  }
}
