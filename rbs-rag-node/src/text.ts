const TOKEN_RE = /[A-Za-z0-9][A-Za-z0-9_'-]*/g;

export function tokenize(text: string): string[] {
  const matches: string[] = [];
  let match: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((match = TOKEN_RE.exec(text)) !== null) {
    matches.push(match[0].toLowerCase());
  }
  return matches;
}

export function cosineSimilarity(left: number[], right: number[]): number {
  if (!left.length || !right.length || left.length !== right.length) return 0;
  let dot = 0, normLeft = 0, normRight = 0;
  for (let i = 0; i < left.length; i++) {
    dot += left[i] * right[i];
    normLeft += left[i] * left[i];
    normRight += right[i] * right[i];
  }
  normLeft = Math.sqrt(normLeft);
  normRight = Math.sqrt(normRight);
  if (normLeft === 0 || normRight === 0) return 0;
  return dot / (normLeft * normRight);
}

export function l2Normalize(values: number[]): number[] {
  let norm = 0;
  for (const v of values) norm += v * v;
  norm = Math.sqrt(norm);
  if (norm === 0) return values;
  return values.map(v => v / norm);
}

export function bm25Scores(
  query: string,
  documents: Record<string, string>,
  k1 = 1.5,
  b = 0.75
): Record<string, number> {
  const queryTerms = tokenize(query);
  const docIds = Object.keys(documents);
  if (!queryTerms.length || !docIds.length) {
    const result: Record<string, number> = {};
    for (const id of docIds) result[id] = 0;
    return result;
  }

  const tokenized: Record<string, string[]> = {};
  const lengths: Record<string, number> = {};
  for (const id of docIds) {
    tokenized[id] = tokenize(documents[id]);
    lengths[id] = tokenized[id].length;
  }
  const avgLength = docIds.reduce((s, id) => s + lengths[id], 0) / Math.max(docIds.length, 1);

  const docFreq: Record<string, number> = {};
  for (const id of docIds) {
    const seen = new Set(tokenized[id]);
    for (const term of seen) {
      docFreq[term] = (docFreq[term] || 0) + 1;
    }
  }

  const totalDocs = docIds.length;
  const scores: Record<string, number> = {};
  for (const id of docIds) {
    const freqs: Record<string, number> = {};
    for (const t of tokenized[id]) freqs[t] = (freqs[t] || 0) + 1;

    let score = 0;
    const docLength = Math.max(lengths[id], 1);
    for (const term of queryTerms) {
      const f = freqs[term] || 0;
      if (f === 0) continue;
      const idf = Math.log(1 + (totalDocs - (docFreq[term] || 0) + 0.5) / ((docFreq[term] || 0) + 0.5));
      const numerator = f * (k1 + 1);
      const denominator = f + k1 * (1 - b + b * docLength / Math.max(avgLength, 1));
      score += idf * numerator / denominator;
    }
    scores[id] = score;
  }
  return scores;
}
