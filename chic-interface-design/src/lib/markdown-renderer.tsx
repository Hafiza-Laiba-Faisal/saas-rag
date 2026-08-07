import React from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ListItem = {
  content: InlineNode[];
  checked?: boolean | null; // null = not a task item, true/false = task item state
  children?: Node[]; // nested blocks (sub-lists, extra paragraphs, etc.)
};

type TableAlign = 'left' | 'center' | 'right' | null;

type Node =
  | { type: 'heading'; level: number; children: InlineNode[] }
  | { type: 'paragraph'; children: InlineNode[] }
  | { type: 'bullet_list'; items: ListItem[] }
  | { type: 'ordered_list'; items: ListItem[]; start: number }
  | { type: 'blockquote'; children: Node[] }
  | { type: 'code_block'; language?: string; code: string }
  | { type: 'hr' }
  | { type: 'table'; header: InlineNode[][]; align: TableAlign[]; rows: InlineNode[][][] };

type InlineNode =
  | { type: 'text'; value: string }
  | { type: 'break' }
  | { type: 'bold'; children: InlineNode[] }
  | { type: 'italic'; children: InlineNode[] }
  | { type: 'bolditalic'; children: InlineNode[] }
  | { type: 'strike'; children: InlineNode[] }
  | { type: 'code'; value: string }
  | { type: 'link'; url: string; text: string }
  | { type: 'image'; url: string; alt?: string }
  | { type: 'map'; url: string; embedUrl: string };

// ---------------------------------------------------------------------------
// Helpers / regexes
// ---------------------------------------------------------------------------

const IMAGE_EXT_RE = /\.(jpg|jpeg|png|gif|svg|webp|bmp)(\?.*)?$/i;
const MAP_URL_RE = /(google\.com\/maps|maps\.google|maps\.app\.goo\.gl|openstreetmap\.org)/i;

const HEADING_RE = /^(#{1,6})\s+(.+?)\s*#*$/;
const HR_RE = /^([-*_])\1{2,}$/;
const FENCE_RE = /^(`{3,}|~{3,})\s*([\w+-]*)\s*$/;
const BLOCKQUOTE_RE = /^>\s?(.*)$/;
const TABLE_SEP_CELL_RE = /^:?-{1,}:?$/;

function isTableSeparatorLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed || !/[-|]/.test(trimmed)) return false;
  const cells = splitTableRow(trimmed);
  if (!cells.length) return false;
  return cells.every((c) => TABLE_SEP_CELL_RE.test(c.trim()));
}
const BULLET_RE = /^([-*•])\s+(.*)$/;
const ORDERED_RE = /^(\d+)[.)]\s+(.*)$/;
const TASK_RE = /^\[( |x|X)\]\s+(.*)$/;

function getIndent(line: string): number {
  let n = 0;
  while (n < line.length && line[n] === ' ') n++;
  return n;
}

function isImageUrl(url: string): boolean {
  const clean = url.split('?')[0].split('#')[0];
  return IMAGE_EXT_RE.test(clean);
}

function isMapUrl(url: string): boolean {
  return MAP_URL_RE.test(url);
}

function makeMapEmbed(url: string): string {
  const match = url.match(/[?&]q=([^&]+)/);
  if (match) return `https://maps.google.com/maps?q=${encodeURIComponent(decodeURIComponent(match[1]))}&output=embed`;
  const atMatch = url.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (atMatch) return `https://maps.google.com/maps?q=${atMatch[1]},${atMatch[2]}&output=embed`;
  const placeMatch = url.match(/\/place\/([^/@?]+)/);
  if (placeMatch) return `https://maps.google.com/maps?q=${encodeURIComponent(decodeURIComponent(placeMatch[1]))}&output=embed`;
  return '';
}

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells: string[] = [];
  let cur = '';
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (ch === '\\' && trimmed[i + 1] === '|') {
      cur += '|';
      i++;
    } else if (ch === '|') {
      cells.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  cells.push(cur.trim());
  return cells;
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export function renderMarkdown(text: string): React.ReactNode {
  if (!text) return null;
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const { blocks } = parseBlocks(lines, 0, 0);
  return <div className="space-y-2 leading-relaxed">{renderBlocks(blocks)}</div>;
}

// ---------------------------------------------------------------------------
// Block parsing
// ---------------------------------------------------------------------------

function parseBlocks(lines: string[], startIdx: number, indent: number): { blocks: Node[]; next: number } {
  const blocks: Node[] = [];
  let i = startIdx;

  while (i < lines.length) {
    const raw = lines[i];
    const trimmedAll = raw.trim();

    if (trimmedAll === '') {
      i++;
      continue;
    }

    const lineIndent = getIndent(raw);
    if (lineIndent < indent) break;

    const content = raw.slice(indent);
    const trimmed = content.trim();

    // Fenced code block
    const fenceMatch = trimmed.match(FENCE_RE);
    if (fenceMatch) {
      const fenceChar = fenceMatch[1][0];
      const lang = fenceMatch[2] || undefined;
      const codeLines: string[] = [];
      i++;
      while (i < lines.length) {
        const closeLine = lines[i].trim();
        const closeRe = fenceChar === '`' ? /^`{3,}\s*$/ : /^~{3,}\s*$/;
        if (closeRe.test(closeLine)) {
          i++;
          break;
        }
        codeLines.push(lines[i].slice(indent));
        i++;
      }
      blocks.push({ type: 'code_block', language: lang, code: codeLines.join('\n') });
      continue;
    }

    // Horizontal rule (only when it isn't actually a list marker line)
    if (HR_RE.test(trimmed)) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    // Heading
    const headMatch = trimmed.match(HEADING_RE);
    if (headMatch) {
      blocks.push({ type: 'heading', level: headMatch[1].length, children: parseInline(headMatch[2]) });
      i++;
      continue;
    }

    // Blockquote
    if (/^>/.test(trimmed)) {
      const quoteLines: string[] = [];
      while (i < lines.length) {
        const t = lines[i].slice(indent);
        const m = t.trim().match(BLOCKQUOTE_RE);
        if (m) {
          quoteLines.push(m[1]);
          i++;
        } else if (t.trim() === '') {
          break;
        } else {
          break;
        }
      }
      const { blocks: innerBlocks } = parseBlocks(quoteLines, 0, 0);
      blocks.push({ type: 'blockquote', children: innerBlocks });
      continue;
    }

    // Table
    if (/\|/.test(trimmed) && i + 1 < lines.length && isTableSeparatorLine(lines[i + 1].slice(indent))) {
      const headerCells = splitTableRow(trimmed);
      const sepCells = splitTableRow(lines[i + 1].slice(indent));
      const align: TableAlign[] = sepCells.map((c) => {
        const left = c.trim().startsWith(':');
        const right = c.trim().endsWith(':');
        if (left && right) return 'center';
        if (right) return 'right';
        if (left) return 'left';
        return null;
      });
      i += 2;
      const rows: InlineNode[][][] = [];
      while (i < lines.length) {
        const rowLine = lines[i];
        const rowIndent = getIndent(rowLine);
        if (rowIndent < indent) break;
        const rowTrimmed = rowLine.slice(indent).trim();
        if (rowTrimmed === '' || !/\|/.test(rowTrimmed)) break;
        rows.push(splitTableRow(rowTrimmed).map(parseInline));
        i++;
      }
      blocks.push({
        type: 'table',
        header: headerCells.map(parseInline),
        align,
        rows,
      });
      continue;
    }

    // Lists (bullet or ordered), with nested-content support
    const bulletMatch = trimmed.match(BULLET_RE);
    const orderedMatch = trimmed.match(ORDERED_RE);
    if (bulletMatch || orderedMatch) {
      const ordered = !!orderedMatch;
      const items: ListItem[] = [];
      const startNum = orderedMatch ? parseInt(orderedMatch[1], 10) : 1;

      while (i < lines.length) {
        const curRaw = lines[i];
        const curIndentAbs = getIndent(curRaw);
        if (curIndentAbs < indent) break;
        const curContent = curRaw.slice(indent);
        const curTrimmed = curContent.trim();
        if (curTrimmed === '') {
          i++;
          continue;
        }
        const bm = curTrimmed.match(BULLET_RE);
        const om = curTrimmed.match(ORDERED_RE);
        const matchesThisKind = ordered ? !!om : !!bm;
        // A differently-indented or differently-typed marker line ends this list level
        if (!matchesThisKind) break;

        const markerText = ordered ? om![2] : bm![2];
        // figure out how many columns the marker itself occupies, to compute
        // the indent threshold for this item's nested/continuation content
        const markerLength = curContent.length - curContent.trimStart().length + (curTrimmed.length - markerText.length);
        const childIndent = indent + markerLength;

        let itemText = markerText;
        let checked: boolean | null = null;
        const taskMatch = itemText.match(TASK_RE);
        if (taskMatch) {
          checked = taskMatch[1].toLowerCase() === 'x';
          itemText = taskMatch[2];
        }

        i++;
        const { blocks: nestedBlocks, next } = parseBlocks(lines, i, childIndent);
        i = next;

        items.push({
          content: parseInline(itemText),
          checked,
          children: nestedBlocks.length ? nestedBlocks : undefined,
        });
      }

      blocks.push(
        ordered
          ? { type: 'ordered_list', items, start: startNum }
          : { type: 'bullet_list', items }
      );
      continue;
    }

    // Paragraph: gather lines until a blank line or a new block type begins
    const paraLines: string[] = [];
    while (i < lines.length) {
      const l = lines[i];
      if (getIndent(l) < indent) break;
      const lc = l.slice(indent);
      const lt = lc.trim();
      if (lt === '') break;
      if (
        FENCE_RE.test(lt) ||
        HR_RE.test(lt) ||
        HEADING_RE.test(lt) ||
        /^>/.test(lt) ||
        BULLET_RE.test(lt) ||
        ORDERED_RE.test(lt)
      )
        break;
      paraLines.push(lc);
      i++;
    }
    if (paraLines.length) {
      // A line ending in two+ spaces, or a backslash, forces a line break
      const joined: string[] = [];
      paraLines.forEach((l, idx) => {
        const isLast = idx === paraLines.length - 1;
        const hardBreak = !isLast && (/ {2,}$/.test(l) || /\\$/.test(l));
        joined.push(l.replace(/ {2,}$/, '').replace(/\\$/, ''));
        if (hardBreak) joined.push('\u0000BREAK\u0000');
      });
      blocks.push({ type: 'paragraph', children: parseInline(joined.join(' ')) });
    }
  }

  return { blocks, next: i };
}

// ---------------------------------------------------------------------------
// Inline parsing
// ---------------------------------------------------------------------------

const INLINE_RE_SOURCE =
  '(!?)\\[([^\\]]*)\\]\\(([^)]+)\\)|(\\*\\*\\*|___)([\\s\\S]+?)\\4|(\\*\\*|__)([\\s\\S]+?)\\6|(~~)([\\s\\S]+?)~~|(`+)([\\s\\S]+?)\\10|(\\*|_)([\\s\\S]+?)\\12|(https?:\\/\\/[^\\s()<>]+(?:\\.[^\\s()<>]+)*[^\\s()<>!.,;:?])';

function parseInline(text: string): InlineNode[] {
  const result: InlineNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  // A fresh RegExp instance per call — parseInline recurses (bold/italic children),
  // and reusing one shared global regex would corrupt lastIndex across nested calls.
  const inlineRe = new RegExp(INLINE_RE_SOURCE, 'g');

  while ((match = inlineRe.exec(text)) !== null) {
    if (match.index > last) {
      pushText(result, text.slice(last, match.index));
    }

    if (match[2] !== undefined) {
      // link / image / map
      const isMarkdownImage = match[1] === '!';
      const linkText = match[2];
      const rawUrl = match[3];
      if (isMarkdownImage) {
        result.push({ type: 'image', url: rawUrl, alt: linkText || undefined });
      } else if (isImageUrl(rawUrl)) {
        result.push({ type: 'image', url: rawUrl, alt: linkText });
      } else if (isMapUrl(rawUrl)) {
        const embedUrl = makeMapEmbed(rawUrl);
        result.push({ type: 'map', url: rawUrl, embedUrl: embedUrl || rawUrl });
      } else {
        result.push({ type: 'link', url: rawUrl, text: linkText });
      }
    } else if (match[5] !== undefined) {
      result.push({ type: 'bolditalic', children: parseInline(match[5]) });
    } else if (match[7] !== undefined) {
      result.push({ type: 'bold', children: parseInline(match[7]) });
    } else if (match[9] !== undefined) {
      result.push({ type: 'strike', children: parseInline(match[9]) });
    } else if (match[11] !== undefined) {
      result.push({ type: 'code', value: match[11] });
    } else if (match[13] !== undefined) {
      result.push({ type: 'italic', children: parseInline(match[13]) });
    } else if (match[14] !== undefined) {
      const url = match[14];
      if (isImageUrl(url)) {
        result.push({ type: 'image', url, alt: undefined });
      } else if (isMapUrl(url)) {
        const embedUrl = makeMapEmbed(url);
        result.push({ type: 'map', url, embedUrl: embedUrl || url });
      } else {
        result.push({ type: 'link', url, text: url });
      }
    }

    last = match.index + match[0].length;
  }

  if (last < text.length) {
    pushText(result, text.slice(last));
  }

  return result.length ? result : [{ type: 'text', value: text }];
}

function pushText(result: InlineNode[], raw: string) {
  const parts = raw.split('\u0000BREAK\u0000');
  parts.forEach((part, idx) => {
    if (part) result.push({ type: 'text', value: part });
    if (idx < parts.length - 1) result.push({ type: 'break' });
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderBlocks(blocks: Node[]): React.ReactNode {
  return blocks.map((block, i) => renderBlock(block, i));
}

function renderBlock(block: Node, key: number): React.ReactNode {
  switch (block.type) {
    case 'heading': {
      const sizes: Record<number, string> = {
        1: 'text-lg font-bold',
        2: 'text-base font-bold',
        3: 'text-sm font-bold',
        4: 'text-sm font-semibold',
        5: 'text-xs font-semibold uppercase tracking-wide',
        6: 'text-xs font-semibold uppercase tracking-wide text-muted-foreground',
      };
      return React.createElement(
        `h${block.level}`,
        { key, className: `${sizes[block.level] || sizes[3]} text-foreground mt-3 mb-1` },
        renderInline(block.children)
      );
    }

    case 'paragraph':
      return (
        <p key={key} className="text-sm">
          {renderInline(block.children)}
        </p>
      );

    case 'hr':
      return <hr key={key} className="my-3 border-border" />;

    case 'blockquote':
      return (
        <blockquote key={key} className="border-l-2 border-primary/50 pl-3 italic text-sm text-muted-foreground space-y-2">
          {renderBlocks(block.children)}
        </blockquote>
      );

    case 'code_block':
      return (
        <div key={key} className="my-2 overflow-hidden rounded-lg border border-border bg-muted/50">
          {block.language && (
            <div className="border-b border-border px-3 py-1 text-xs font-mono text-muted-foreground">
              {block.language}
            </div>
          )}
          <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
            <code className="font-mono">{block.code}</code>
          </pre>
        </div>
      );

    case 'bullet_list':
      return (
        <ul key={key} className="space-y-1 pl-1">
          {block.items.map((item, j) => (
            <li key={j} className="flex items-start gap-2 text-sm">
              {item.checked !== null && item.checked !== undefined ? (
                <span
                  className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                    item.checked ? 'border-primary bg-primary text-primary-foreground' : 'border-border'
                  }`}
                >
                  {item.checked ? '✓' : ''}
                </span>
              ) : (
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              )}
              <span className="flex-1">
                {renderInline(item.content)}
                {item.children && <div className="mt-1 space-y-1">{renderBlocks(item.children)}</div>}
              </span>
            </li>
          ))}
        </ul>
      );

    case 'ordered_list':
      return (
        <ol key={key} className="space-y-1 pl-1">
          {block.items.map((item, j) => (
            <li key={j} className="flex items-start gap-2 text-sm">
              <span className="mt-0.5 shrink-0 font-semibold text-primary">{block.start + j}.</span>
              <span className="flex-1">
                {renderInline(item.content)}
                {item.children && <div className="mt-1 space-y-1">{renderBlocks(item.children)}</div>}
              </span>
            </li>
          ))}
        </ol>
      );

    case 'table':
      return (
        <div key={key} className="my-2 overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-muted/50">
                {block.header.map((cell, ci) => (
                  <th
                    key={ci}
                    className="border-b border-border px-3 py-2 font-semibold text-foreground"
                    style={{ textAlign: block.align[ci] || 'left' }}
                  >
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 1 ? 'bg-muted/20' : undefined}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="border-b border-border px-3 py-2 align-top"
                      style={{ textAlign: block.align[ci] || 'left' }}
                    >
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    default:
      return null;
  }
}

function renderInline(nodes: InlineNode[]): React.ReactNode {
  return nodes.map((node, i) => {
    switch (node.type) {
      case 'break':
        return <br key={i} />;
      case 'bold':
        return (
          <strong key={i} className="font-semibold text-foreground">
            {renderInline(node.children)}
          </strong>
        );
      case 'italic':
        return (
          <em key={i} className="italic">
            {renderInline(node.children)}
          </em>
        );
      case 'bolditalic':
        return (
          <strong key={i} className="font-semibold italic text-foreground">
            {renderInline(node.children)}
          </strong>
        );
      case 'strike':
        return (
          <span key={i} className="line-through text-muted-foreground">
            {renderInline(node.children)}
          </span>
        );
      case 'code':
        return (
          <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
            {node.value}
          </code>
        );
      case 'link':
        return (
          <a
            key={i}
            href={node.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline underline-offset-2 hover:opacity-80 break-all"
          >
            {node.text}
          </a>
        );
      case 'image':
        return (
          <span key={i} className="block my-2">
            <img
              src={node.url}
              alt={node.alt || ''}
              loading="lazy"
              className="max-w-full rounded-lg border border-border"
              style={{ maxHeight: 300 }}
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
            {node.alt && <span className="block mt-1 text-xs text-muted-foreground">{node.alt}</span>}
          </span>
        );
      case 'map':
        return (
          <span key={i} className="block my-2">
            <a
              href={node.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2 hover:opacity-80 text-xs mb-1 inline-block"
            >
              📍 Open in Google Maps
            </a>
            {node.embedUrl && (
              <iframe
                src={node.embedUrl}
                width="100%"
                height="200"
                className="rounded-lg border border-border"
                loading="lazy"
                allowFullScreen
              />
            )}
          </span>
        );
      case 'text':
      default:
        return node.value;
    }
  });
}
