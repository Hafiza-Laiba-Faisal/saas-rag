import fs from 'fs';
import path from 'path';

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp']);

export function isImageFile(filePath: string): boolean {
  return IMAGE_EXTS.has(path.extname(filePath).toLowerCase());
}

export function isPdfFile(filePath: string): boolean {
  return path.extname(filePath).toLowerCase() === '.pdf';
}

export async function ocrFile(
  filePath: string,
  ocrServiceUrl: string,
  ocrApiKey: string
): Promise<{ text: string; ocrEngine: string | null }> {
  const fileName = path.basename(filePath);
  const fileBuffer = fs.readFileSync(filePath);
  const isPdf = isPdfFile(filePath);

  const endpoint = isPdf ? `${ocrServiceUrl}/ocr/pdf` : `${ocrServiceUrl}/ocr/image`;

  const ext = path.extname(filePath).toLowerCase();
  let mimeType = 'application/octet-stream';
  if (ext === '.pdf') mimeType = 'application/pdf';
  else if (ext === '.png') mimeType = 'image/png';
  else if (ext === '.jpg' || ext === '.jpeg') mimeType = 'image/jpeg';
  else if (ext === '.webp') mimeType = 'image/webp';
  else if (ext === '.bmp') mimeType = 'image/bmp';
  else if (ext === '.tiff' || ext === '.tif') mimeType = 'image/tiff';

  try {
    const blob = new Blob([fileBuffer], { type: mimeType });
    const formData = new FormData();
    formData.append('file', blob, fileName);

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'X-API-Key': ocrApiKey },
      body: formData,
      signal: AbortSignal.timeout(120000),
    });

    if (!response.ok) {
      console.error(`OCR Service Error: HTTP ${response.status} - ${await response.text()}`);
      return { text: '', ocrEngine: null };
    }

    const result = await response.json() as any;
    const pages = result.pages || [];
    const text = pages.map((p: any) => p.full_text || '').join('\n\n').trim();
    return { text, ocrEngine: 'ocr-service' };
  } catch {
    return { text: '', ocrEngine: null };
  }
}
