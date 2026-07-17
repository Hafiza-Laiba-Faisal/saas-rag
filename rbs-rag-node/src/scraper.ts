import * as cheerio from 'cheerio';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { execSync } from 'child_process';

const PRIVATE_NETWORKS = [
  /^https?:\/\/localhost/i,
  /^https?:\/\/127\./,
  /^https?:\/\/10\./,
  /^https?:\/\/172\.(1[6-9]|2\d|3[01])\./,
  /^https?:\/\/192\.168\./,
  /^https?:\/\/0\.0\.0\.0/,
  /^https?:\/\/169\.254\./,
  /^https?:\/\/\[::1\]/,
  /^https?:\/\/\[f[cd]/i,
];

export interface ScrapeResult {
  jobId: string;
  url: string;
  title: string;
  description: string;
  text: string;
  links: string[];
  images: string[];
  wordCount: number;
  savedFilePath: string | null;
  error: string | null;
  processingTimeMs: number;
}

export interface ScrapeRequest {
  url: string;
  crawl?: boolean;
  maxPages?: number;
  maxDepth?: number;
  fullSite?: boolean;
}

function validateUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return 'Only HTTP and HTTPS URLs are allowed';
    }
    for (const pattern of PRIVATE_NETWORKS) {
      if (pattern.test(url)) {
        return 'Scraping private/internal networks is not allowed';
      }
    }
    return null;
  } catch {
    return 'Invalid URL format';
  }
}

async function fetchUrl(url: string, signal?: AbortSignal): Promise<{ html: string; contentType: string }> {
  const response = await fetch(url, {
    signal,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Referer': 'https://www.google.com/',
      'Cache-Control': 'no-cache',
    },
    redirect: 'follow',
  });

  const contentType = response.headers.get('content-type') || '';

  if (response.status === 403 || response.status === 503) {
    const body = await response.text();
    if (body.includes('cloudflare') || body.includes('Attention Required') || body.includes('cf-browser-verification')) {
      try {
        const curlResult = execSync(
          `curl -sL '${url.replace(/'/g, "'\\''")}' ` +
          `-A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36' ` +
          `-H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' ` +
          `-H 'Accept-Language: en-US,en;q=0.9' ` +
          `-H 'Referer: https://www.google.com/' ` +
          `--max-time 15`,
          { encoding: 'utf-8', timeout: 20000 }
        );
        if (curlResult && curlResult.length > 500) {
          return { html: curlResult, contentType };
        }
      } catch {}
    }
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const html = await response.text();
  return { html, contentType };
}

function stripHtmlTags(text: string): string {
  return text.replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#8217;/g, "'")
    .replace(/&#822[01];/g, '"')
    .replace(/&#\d+;/g, ' ');
}

function extractContent(html: string, pageUrl?: string): { title: string; description: string; text: string; links: string[]; images: string[] } {
  const $ = cheerio.load(html);
  const baseUrl = pageUrl || 'https://example.com';

  const title = $('title').first().text().trim() || $('h1').first().text().trim() || '';

  const description =
    $('meta[name="description"]').attr('content')?.trim() ||
    $('meta[property="og:description"]').attr('content')?.trim() ||
    '';

  const links: string[] = [];
  $('a[href]').each((_, el) => {
    const href = $(el).attr('href');
    if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {
      try {
        const url = new URL(href, baseUrl);
        links.push(url.href);
      } catch {}
    }
  });

  const images: string[] = [];
  $('img[src]').each((_, el) => {
    const src = $(el).attr('src');
    if (src) {
      try {
        images.push(new URL(src, baseUrl).href);
      } catch {}
    }
  });

  const articleSelectors = 'article, [role="main"], main, .content, .post, .article, #content, #main, .wpb-content-wrapper, .entry-content, .post-content, .page-content, .site-content, #primary, .vc_row, .dfd-content-wrap';
  let $content = $(articleSelectors).first();
  if (!$content.length) {
    $content = $('body');
  }

  $content.find('script, style, nav, header, footer, iframe, noscript, svg, form, .dfd-frame-line, .form-search-section').remove();
  const text = $content.text()
    .replace(/\s+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  const wordCount = text.split(/\s+/).filter(Boolean).length;

  return { title, description, text, links, images };
}

function isWordPressSite(html: string): boolean {
  return /wp-content|wp-includes|wp-json|wp-admin/i.test(html);
}

function extractJsonLd(html: string): string[] {
  const texts: string[] = [];
  const matches = html.match(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi);
  if (matches) {
    for (const match of matches) {
      const json = match.replace(/<\/?script[^>]*>/gi, '').trim();
      try {
        const data = JSON.parse(json);
        const extract = (obj: any): void => {
          if (!obj) return;
          if (typeof obj === 'string') texts.push(obj);
          else if (Array.isArray(obj)) obj.forEach(extract);
          else if (typeof obj === 'object') {
            for (const val of Object.values(obj)) extract(val);
          }
        };
        extract(data);
      } catch {}
    }
  }
  return texts;
}

async function fetchWordPressContent(url: string): Promise<{ title: string; text: string } | null> {
  try {
    const parsed = new URL(url);
    const baseUrl = `${parsed.protocol}//${parsed.host}`;
    const langPath = parsed.pathname.match(/^\/([a-z]{2})\//)?.[1] || '';
    const pathParts = parsed.pathname.replace(/\/$/, '').split('/').filter(Boolean);
    let slug = pathParts.length > 1 ? pathParts[pathParts.length - 1] : 'home';

    const apiBase = langPath ? `${baseUrl}/${langPath}/wp-json` : `${baseUrl}/wp-json`;
    const endpoints = [
      `${apiBase}/wp/v2/pages?slug=${slug}`,
      `${apiBase}/wp/v2/posts?slug=${slug}`,
      `${baseUrl}/wp-json/wp/v2/pages?slug=${slug}`,
      `${baseUrl}/wp-json/wp/v2/posts?slug=${slug}`,
    ];

    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' },
          signal: AbortSignal.timeout(5000),
        });
        if (!response.ok) continue;
        const data = await response.json();
        if (!Array.isArray(data) || data.length === 0) continue;

        const page = data[0];
        const rawTitle = page.title?.rendered || page.title || '';
        let rawContent = page.content?.rendered || page.content || '';

        rawContent = rawContent
          .replace(/<script[\s\S]*?<\/script>/gi, ' ')
          .replace(/<style[\s\S]*?<\/style>/gi, ' ')
          .replace(/\[vc_row[^\]]*\]/gi, ' ')
          .replace(/\[\/vc_row\]/gi, ' ')
          .replace(/\[vc_column[^\]]*\]/gi, ' ')
          .replace(/\[\/vc_column\]/gi, ' ')
          .replace(/\[vc_column_text[^\]]*\]/gi, ' ')
          .replace(/\[\/vc_column_text\]/gi, ' ')
          .replace(/\[vc_empty_space[^\]]*\]/gi, ' ')
          .replace(/\[vc_single_image[^\]]*\]/gi, ' ')
          .replace(/\[dfd_spacer[^\]]*\]/gi, ' ')
          .replace(/\[dfd_heading[^\]]*\]([\s\S]*?)\[\/dfd_heading\]/gi, '$1 ')
          .replace(/\[dfd_button[^\]]*\]([\s\S]*?)\[\/dfd_button\]/gi, '$1 ')
          .replace(/\[dfd_[a-z_]+\][\s\S]*?\[\/dfd_[a-z_]+\]/gi, ' ')
          .replace(/\[rev_slider[^\]]*\][\s\S]*?\[\/rev_slider\]/gi, ' ')
          .replace(/\[[a-z_]+\][\s\S]*?\[\/[a-z_]+\]/gi, ' ')
          .replace(/\[[a-z_]+[^\]]*\]/gi, ' ')
          .replace(/\[\/[a-z_]+]/gi, ' ');

        const $ = cheerio.load('<div>' + rawContent + '</div>');
        $('script, style, iframe, noscript, svg, form').remove();
        const text = $('div').text()
          .replace(/\s+/g, ' ')
          .trim();

        if (text.length > 0) {
          return { title: stripHtmlTags(rawTitle).trim(), text };
        }
      } catch {}
    }
    return null;
  } catch {
    return null;
  }
}

async function scrapeSinglePage(
  url: string,
  signal?: AbortSignal
): Promise<{ title: string; description: string; text: string; links: string[]; images: string[] }> {
  const { html, contentType } = await fetchUrl(url, signal);

  if (!contentType.includes('text/html') && !contentType.includes('application/xhtml')) {
    return { title: '', description: '', text: '', links: [], images: [] };
  }

  let result = extractContent(html, url);

  if (result.text.split(/\s+/).filter(Boolean).length < 50) {
    const jsonLdTexts = extractJsonLd(html);
    const combinedJsonLd = jsonLdTexts.filter(t => t.length > 20).join(' ');
    if (combinedJsonLd.length > result.text.length) {
      result.text = combinedJsonLd;
    }
  }

  if (result.text.split(/\s+/).filter(Boolean).length < 50 && isWordPressSite(html)) {
    const wpContent = await fetchWordPressContent(url);
    if (wpContent && wpContent.text.length > result.text.length) {
      result = { ...result, title: wpContent.title || result.title, text: wpContent.text };
    }
  }

  const wordCount = result.text.split(/\s+/).filter(Boolean).length;
  if (wordCount < 20) {
    const bodyText = cheerio.load(html)('body').text()
      .replace(/\s+/g, ' ')
      .trim();
    const lines = bodyText.split(/\s{2,}|\n+/).filter(l => l.trim().length > 30);
    if (lines.length > 0) {
      result.text = lines.join('\n');
    }
  }

  return result;
}

async function crawlPages(
  startUrl: string,
  maxPages: number,
  maxDepth: number,
  signal?: AbortSignal
): Promise<{ title: string; description: string; text: string; links: string[]; images: string[] }> {
  const visited = new Set<string>();
  const queue: { url: string; depth: number }[] = [{ url: startUrl, depth: 0 }];
  const startParsed = new URL(startUrl);
  const baseDomain = startParsed.hostname.replace(/^www\./, '');
  const allTexts: string[] = [];
  let allTitle = '';
  let allDescription = '';
  const allLinks = new Set<string>();
  const allImages = new Set<string>();

  while (queue.length > 0 && visited.size < maxPages) {
    const { url, depth } = queue.shift()!;
    if (visited.has(url) || depth > maxDepth) continue;
    visited.add(url);

    try {
      const result = await scrapeSinglePage(url, signal);
      if (result.text.trim()) {
        allTexts.push(`--- Page: ${url} ---\n${result.text}`);
      }
      if (!allTitle && result.title) allTitle = result.title;
      if (!allDescription && result.description) allDescription = result.description;
      result.links.forEach(l => allLinks.add(l));
      result.images.forEach(i => allImages.add(i));

      if (depth < maxDepth) {
        for (const link of result.links) {
          try {
            const parsed = new URL(link);
            const linkDomain = parsed.hostname.replace(/^www\./, '');
            if (linkDomain === baseDomain && !visited.has(link) && !parsed.pathname.match(/\.(pdf|jpg|png|gif|zip|css|js)$/i)) {
              queue.push({ url: link, depth: depth + 1 });
            }
          } catch {}
        }
      }
    } catch {}
  }

  return {
    title: allTitle,
    description: allDescription,
    text: allTexts.join('\n\n'),
    links: Array.from(allLinks),
    images: Array.from(allImages),
  };
}

export async function scrapeUrl(
  request: ScrapeRequest,
  tenantDir: string,
  signal?: AbortSignal
): Promise<ScrapeResult> {
  const startTime = performance.now();
  const jobId = uuidv4();

  const validationError = validateUrl(request.url);
  if (validationError) {
    return {
      jobId, url: request.url, title: '', description: '', text: '',
      links: [], images: [], wordCount: 0, savedFilePath: null,
      error: validationError, processingTimeMs: 0,
    };
  }

  try {
    const shouldCrawl = request.crawl || request.fullSite;
    const maxPages = request.maxPages || (request.fullSite ? 50 : 10);
    const maxDepth = request.maxDepth || (request.fullSite ? 3 : 1);

    let result: { title: string; description: string; text: string; links: string[]; images: string[] };

    if (shouldCrawl) {
      result = await crawlPages(request.url, maxPages, maxDepth, signal);
    } else {
      result = await scrapeSinglePage(request.url, signal);
    }

    const wordCount = result.text.split(/\s+/).filter(Boolean).length;
    const siteName = new URL(request.url).hostname.replace(/^www\./, '').replace(/[^a-z0-9]/gi, '_');
    const titleSlug = (result.title || 'page').toLowerCase().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').slice(0, 40);
    const scrapeType = shouldCrawl ? 'fullsite' : 'page';
    const fileName = `${siteName}_${titleSlug}_${scrapeType}_${jobId.slice(0, 8)}.txt`;
    const filePath = path.join(tenantDir, fileName);

    const content = [
      `URL: ${request.url}`,
      `Title: ${result.title}`,
      `Description: ${result.description}`,
      '',
      result.text,
    ].join('\n');

    fs.mkdirSync(tenantDir, { recursive: true });
    fs.writeFileSync(filePath, content, 'utf-8');

    return {
      jobId, url: request.url, title: result.title, description: result.description,
      text: result.text, links: result.links, images: result.images,
      wordCount, savedFilePath: fileName, error: null,
      processingTimeMs: Math.round(performance.now() - startTime),
    };
  } catch (err: any) {
    return {
      jobId, url: request.url, title: '', description: '', text: '',
      links: [], images: [], wordCount: 0, savedFilePath: null,
      error: err.message || 'Unknown error',
      processingTimeMs: Math.round(performance.now() - startTime),
    };
  }
}
