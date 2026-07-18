/**
 * Markdown renderer for LLM responses.
 * Handles: **bold**, bullet lists (- / * / •), numbered lists, blank line paragraphs.
 */

type Node =
  | { type: "paragraph"; children: InlineNode[] }
  | { type: "bullet_list"; items: InlineNode[][] }
  | { type: "ordered_list"; items: InlineNode[][] };

type InlineNode =
  | { type: "text"; value: string }
  | { type: "bold"; value: string };

export function renderMarkdown(text: string): React.ReactNode {
  if (!text) return null;
  const blocks = parseBlocks(text);
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((block, i) => {
        if (block.type === "paragraph") {
          return (
            <p key={i} className="text-sm">
              {renderInline(block.children)}
            </p>
          );
        }
        if (block.type === "bullet_list") {
          return (
            <ul key={i} className="space-y-1 pl-1">
              {block.items.map((item, j) => (
                <li key={j} className="flex items-start gap-2 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span>{renderInline(item)}</span>
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === "ordered_list") {
          return (
            <ol key={i} className="space-y-1 pl-1">
              {block.items.map((item, j) => (
                <li key={j} className="flex items-start gap-2 text-sm">
                  <span className="mt-0.5 shrink-0 font-semibold text-primary">{j + 1}.</span>
                  <span>{renderInline(item)}</span>
                </li>
              ))}
            </ol>
          );
        }
        return null;
      })}
    </div>
  );
}

// ─── Block parser ────────────────────────────────────────────────────────────

function parseBlocks(text: string): Node[] {
  const lines = text.split("\n");
  const blocks: Node[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) { i++; continue; }

    // Bullet list item
    if (/^[-*•]\s+/.test(trimmed)) {
      const items: InlineNode[][] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(parseInline(lines[i].trim().replace(/^[-*•]\s+/, "")));
        i++;
      }
      blocks.push({ type: "bullet_list", items });
      continue;
    }

    // Ordered list item
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: InlineNode[][] = [];
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        items.push(parseInline(lines[i].trim().replace(/^\d+[.)]\s+/, "")));
        i++;
      }
      blocks.push({ type: "ordered_list", items });
      continue;
    }

    // Paragraph — collect consecutive non-list lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^[-*•]\s+/.test(lines[i].trim()) &&
      !/^\d+[.)]\s+/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i].trim());
      i++;
    }
    if (paraLines.length) {
      blocks.push({ type: "paragraph", children: parseInline(paraLines.join(" ")) });
    }
  }

  return blocks;
}

// ─── Inline parser ───────────────────────────────────────────────────────────

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  const boldRegex = /\*\*(.+?)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = boldRegex.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push({ type: "text", value: text.slice(last, match.index) });
    }
    nodes.push({ type: "bold", value: match[1] });
    last = match.index + match[0].length;
  }

  if (last < text.length) {
    nodes.push({ type: "text", value: text.slice(last) });
  }

  return nodes.length ? nodes : [{ type: "text", value: text }];
}

function renderInline(nodes: InlineNode[]): React.ReactNode {
  return nodes.map((node, i) => {
    if (node.type === "bold") {
      return <strong key={i} className="font-semibold text-foreground">{node.value}</strong>;
    }
    return node.value;
  });
}
