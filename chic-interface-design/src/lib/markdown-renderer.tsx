import React from 'react';

type InlineNode =
  | { type: 'text'; value: string }
  | { type: 'break' }
  | { type: 'bold'; children: InlineNode[] }
  | { type: 'italic'; children: InlineNode[] }
  | { type: 'code'; value: string }
  | { type: 'link'; url: string; text: string }
  | { type: 'image'; url: string; alt?: string };

type Block =
  | { type: 'heading'; level: number; children: InlineNode[] }
  | { type: 'paragraph'; children: InlineNode[] }
  | { type: 'bullet_list'; items: InlineNode[][] }
  | { type: 'ordered_list'; items: InlineNode[][]; start: number }
  | { type: 'blockquote'; children: Block[] }
  | { type: 'hr' }
  | { type: 'code_block'; language?: string; code: string };

const IMAGE_EXT_RE = /\.(jpg|jpeg|png|gif|svg|webp|bmp)(\?.*)?$/i;
const MAP_URL_RE = /(google\.com\/maps|maps\.google|maps\.app\.goo\.gl|openstreetmap\.org)/i;

function normalizeMarkdownText(text: string): string {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function isImageUrl(url: string): boolean {
  if (!url) return false;
  try { new URL(url); } catch { return false; }
  const clean = url.split('?')[0].split('#')[0].toLowerCase();
  // File extension check
  if (IMAGE_EXT_RE.test(clean)) return true;
  // Common image path patterns
  if (/\/(photos?|images?|img|media|uploads?|assets?|gallery|foto|picture|pic)\//i.test(url)) return true;
  // Cloudinary, imgix, twicpics and similar CDNs
  if (/cloudinary\.com|imgix\.net|imagekit\.io|twicpics\.com|images\.unsplash\.com/.test(url)) return true;
  return false;
}

function parseInline(text: string): InlineNode[] {
  const result: InlineNode[] = [];
  let i = 0;

  while (i < text.length) {
    const char = text[i];
    if (char === '\n') {
      result.push({ type: 'break' });
      i++;
      continue;
    }

    if (text.startsWith('![', i)) {
      const closeAlt = text.indexOf(']', i + 2);
      if (closeAlt !== -1) {
        const alt = text.slice(i + 2, closeAlt);
        // Check if followed by (url)
        if (text[closeAlt + 1] === '(') {
          const closeUrl = text.indexOf(')', closeAlt + 2);
          if (closeUrl !== -1) {
            const url = text.slice(closeAlt + 2, closeUrl).trim();
            // Render as image if it's any valid http/https URL — if broken, onError hides it
            if (url && /^https?:\/\//i.test(url)) {
              result.push({ type: 'image', url, alt: alt || undefined });
              i = closeUrl + 1;
              continue;
            }
          }
        }
        // ![alt] without url — render as italic caption
        if (alt) {
          result.push({ type: 'italic', children: [{ type: 'text', value: alt }] });
          i = closeAlt + 1;
          continue;
        }
      }
    }

    if (text[i] === '[') {
      const close = text.indexOf('](', i + 1);
      const end = close !== -1 ? text.indexOf(')', close + 2) : -1;
      if (close !== -1 && end !== -1) {
        const label = text.slice(i + 1, close);
        const url = text.slice(close + 2, end);
        result.push({ type: 'link', url, text: label || url });
        i = end + 1;
        continue;
      }
    }

    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2);
      if (end !== -1) {
        result.push({ type: 'bold', children: parseInline(text.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }

    if (text.startsWith('__', i)) {
      const end = text.indexOf('__', i + 2);
      if (end !== -1) {
        result.push({ type: 'bold', children: parseInline(text.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }

    if (text.startsWith('*', i) && !text.startsWith('**', i)) {
      const end = text.indexOf('*', i + 1);
      if (end !== -1) {
        result.push({ type: 'italic', children: parseInline(text.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }

    if (text.startsWith('_', i) && !text.startsWith('__', i)) {
      const end = text.indexOf('_', i + 1);
      if (end !== -1) {
        result.push({ type: 'italic', children: parseInline(text.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }

    if (text.startsWith('`', i)) {
      const end = text.indexOf('`', i + 1);
      if (end !== -1) {
        result.push({ type: 'code', value: text.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }

    if (/^https?:\/\//.test(text.slice(i))) {
      const match = text.slice(i).match(/^https?:\/\/[^\s)]+/);
      if (match) {
        const url = match[0];
        result.push({ type: 'link', url, text: url });
        i += url.length;
        continue;
      }
    }

    result.push({ type: 'text', value: char });
    i++;
  }

  return result;
}

function parseBlocks(lines: string[]): { blocks: Block[] } {
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const trimmed = raw.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // allow headings even when there's no separating space (e.g. "###**Bold**")
    // but avoid matching strings of 7+ hashes as headings
    const headingMatch = trimmed.match(/^(#{1,6})(?!#)\s*(.*)$/);
    if (headingMatch) {
      blocks.push({ type: 'heading', level: headingMatch[1].length, children: parseInline(headingMatch[2]) });
      i++;
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = [];
      while (i < lines.length) {
        const line = lines[i].trim();
        if (!line) break;
        if (!/^>\s?/.test(line)) break;
        quoteLines.push(line.replace(/^>\s?/, '').trim());
        i++;
      }
      const nested = parseBlocks(quoteLines);
      blocks.push({ type: 'blockquote', children: nested.blocks });
      continue;
    }

    if (/^([-*_])\1{2,}$/.test(trimmed)) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    if (/^([-*+])\s+/.test(trimmed)) {
      const items: InlineNode[][] = [];
      while (i < lines.length) {
        const current = lines[i].trim();
        if (!current) break;
        const match = current.match(/^([-*+])\s+(.*)$/);
        if (!match) break;
        items.push(parseInline(match[2]));
        i++;
      }
      blocks.push({ type: 'bullet_list', items });
      continue;
    }

    if (/^(\d+)\.?\s+/.test(trimmed)) {
      const items: InlineNode[][] = [];
      let start = 1;
      while (i < lines.length) {
        const current = lines[i].trim();
        if (!current) break;
        const match = current.match(/^(\d+)\.?\s+(.*)$/);
        if (!match) break;
        start = parseInt(match[1], 10);
        items.push(parseInline(match[2]));
        i++;
      }
      blocks.push({ type: 'ordered_list', items, start });
      continue;
    }

    const paragraphLines: string[] = [];
    while (i < lines.length) {
      const current = lines[i].trim();
      if (!current) break;
      if (/^(#{1,6})(?!\#)\s*/.test(current) || /^>\s?/.test(current) || /^([-*_])\1{2,}$/.test(current) || /^([-*+])\s+/.test(current) || /^(\d+)\.?\s+/.test(current)) {
        break;
      }
      paragraphLines.push(lines[i]);
      i++;
    }

    if (paragraphLines.length) {
      blocks.push({ type: 'paragraph', children: parseInline(paragraphLines.join(' ')) });
      continue;
    }

    i++;
  }

  return { blocks };
}

function renderInline(nodes: InlineNode[]): React.ReactNode {
  return nodes.map((node, index) => {
    switch (node.type) {
      case 'break':
        return <br key={index} />;
      case 'bold':
        return <strong key={index} className="font-semibold text-foreground">{renderInline(node.children)}</strong>;
      case 'italic':
        return <em key={index} className="italic">{renderInline(node.children)}</em>;
      case 'code':
        return <code key={index} className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{node.value}</code>;
      case 'link': {
        const isMap = MAP_URL_RE.test(node.url);
        // Build Google Maps embed URL from share/search link
        const getEmbedUrl = (url: string): string | null => {
          try {
            // Handle maps.google.com/maps?q=... or google.com/maps/search/...
            const parsed = new URL(url);
            const q = parsed.searchParams.get('q') || parsed.searchParams.get('query');
            if (q) return `https://maps.google.com/maps?q=${encodeURIComponent(q)}&output=embed`;
            // Handle /maps/place/NAME/@lat,lng,zoom format
            const placeMatch = url.match(/\/maps\/place\/([^/@]+)/);
            if (placeMatch) return `https://maps.google.com/maps?q=${encodeURIComponent(decodeURIComponent(placeMatch[1]))}&output=embed`;
            // Fallback: append output=embed
            if (url.includes('google.com/maps')) {
              const sep = url.includes('?') ? '&' : '?';
              return url + sep + 'output=embed';
            }
          } catch {}
          return null;
        };
        return (
          <span key={index} className="inline">
            <a href={node.url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 break-all">
              {node.text}
            </a>
            {isMap && (() => {
              const embedUrl = getEmbedUrl(node.url);
              return embedUrl ? (
                <span className="mt-2 block rounded-lg overflow-hidden border border-border">
                  <iframe
                    src={embedUrl}
                    width="100%"
                    height="260"
                    style={{ border: 0, display: 'block' }}
                    allowFullScreen
                    loading="lazy"
                    referrerPolicy="no-referrer-when-downgrade"
                    title="Map"
                  />
                </span>
              ) : null;
            })()}
          </span>
        );
      }
      case 'image':
        return (
          <span key={index} className="my-2 block">
            <img
              src={node.url}
              alt={node.alt || ''}
              loading="lazy"
              className="max-w-full rounded-lg border border-border"
              style={{ maxHeight: 300 }}
              onError={(e) => {
                // Hide broken images gracefully
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
            {node.alt && (
              <span className="mt-1 block text-[11px] text-muted-foreground italic">{node.alt}</span>
            )}
          </span>
        );
      case 'text':
      default:
        return <React.Fragment key={index}>{node.value}</React.Fragment>;
    }
  });
}

function renderBlock(block: Block, key: number): React.ReactNode {
  switch (block.type) {
    case 'heading':
      return React.createElement(`h${block.level}`, { key, className: 'mt-3 mb-1 font-semibold text-foreground' }, renderInline(block.children));
    case 'paragraph':
      return <p key={key} className="text-sm leading-6">{renderInline(block.children)}</p>;
    case 'bullet_list':
      return (
        <ul key={key} className="ml-4 list-disc space-y-1 text-sm">
          {block.items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ul>
      );
    case 'ordered_list':
      return (
        <ol key={key} className="ml-4 list-decimal space-y-1 text-sm" start={block.start}>
          {block.items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ol>
      );
    case 'blockquote':
      return <blockquote key={key} className="border-l-2 border-primary/40 pl-3 italic text-sm text-muted-foreground">{block.children.map((child, idx) => renderBlock(child, idx))}</blockquote>;
    case 'hr':
      return <hr key={key} className="my-3 border-border" />;
    case 'code_block':
      return (
        <pre key={key} className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 text-xs">
          <code>{block.code}</code>
        </pre>
      );
    default:
      return null;
  }
}

export function renderMarkdown(text: string): React.ReactNode {
  if (!text) return null;
  const normalized = normalizeMarkdownText(text);
  if (!normalized) return null;
  const { blocks } = parseBlocks(normalized.split('\n'));
  return <div className="space-y-2 leading-relaxed">{blocks.map((block, index) => renderBlock(block, index))}</div>;
}
