/**
 * LLM response parser — keeps it simple.
 * Instead of splitting into sections (which caused duplicate/missing content),
 * we just pass the raw text through and let renderMarkdown handle formatting.
 */

export interface ParsedContent {
  plainText: string;
  sections: Array<{
    title: string;
    content: string;
    items?: string[];
  }>;
}

/**
 * Returns a single-section ParsedContent so the rendering path
 * just calls renderMarkdown on the full text — no splitting.
 */
export function parseLLMResponse(rawText: string): ParsedContent {
  return {
    plainText: rawText,
    sections: [{ title: "Response", content: rawText }],
  };
}

export function renderParsedContent(parsed: ParsedContent): string {
  return parsed.plainText;
}
