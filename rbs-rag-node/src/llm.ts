import { GoogleGenerativeAI } from '@google/generative-ai';
import OpenAI from 'openai';
import { StreamingChunk } from './types/models.js';

const HTML_TAG_RE = /<\/?[a-zA-Z][a-zA-Z0-9]*[^>]*>/g;
const BROKEN_TAG_RE = /(?<!<)(strong|em|b|i|p|u|s|span|div|h[1-6]|li|ul|ol|br|hr|a|img|table|tr|td|th)\s*>/gi;
const OPEN_BROKEN_TAG_RE = /<\s*(strong|em|b|i|p|u|s|span|div|h[1-6]|li|ul|ol|br|hr|a|img|table|tr|td|th)\s*$/gi;

function cleanLlmText(text: string): string {
  let result = text.normalize('NFKC');
  result = result.replace(HTML_TAG_RE, '');
  result = result.replace(BROKEN_TAG_RE, '');
  result = result.replace(OPEN_BROKEN_TAG_RE, ' ');
  result = result.replace(/[ \t]+/g, ' ');
  result = result.replace(/\n{3,}/g, '\n\n');
  return result.trim();
}

export function buildRagMessages(
  query: string,
  contexts: any[],
  sessionMemory = '',
  systemPrompt?: string
): Array<{ role: string; content: string }> {
  const contextLines: string[] = [];
  for (let i = 0; i < contexts.length; i++) {
    const result = contexts[i];
    const metadata = result.chunk.metadata;
    const documentName = metadata.document_name || 'unknown document';
    const section = metadata.section;
    let label = `[${i + 1}] ${documentName}`;
    if (section) label += ` / ${section}`;
    contextLines.push(`${label}\n${result.chunk.text}`);
  }

  const memoryBlock = sessionMemory ? `\nSession memory:\n${sessionMemory}\n` : '';
  const contextBlock = contextLines.length ? contextLines.join('\n\n') : 'No retrieved context.';

  const defaultPrompt =
    'You are a multilingual enterprise knowledge assistant. ' +
    'Always respond in the same language as the user\'s question. ' +
    'Answer only from the supplied context. ' +
    'If the context is insufficient, state what information is missing rather than guessing. ' +
    'Cite evidence with bracketed numbers like [1]. ' +
    'Be concise, professional, and helpful. ' +
    'Never fabricate URLs, statistics, or facts.\n\n' +
    'OUTPUT FORMAT:\n' +
    '- Use **bold** for key terms or hotel names.\n' +
    '- Use bullet lists for amenities, services, or features.\n' +
    '- Never output HTML tags, HTML fragments, or broken tags.\n' +
    '- Before responding, remove all HTML, broken tags, and normalize whitespace.\n' +
    '- Ensure proper spacing between words.';

  const system = systemPrompt || defaultPrompt;

  return [
    { role: 'system', content: system },
    {
      role: 'user',
      content: `${memoryBlock}Retrieved context:\n${contextBlock}\n\nUser question: ${query}`,
    },
  ];
}

export class LLMClient {
  private config: {
    provider: string;
    apiKey: string;
    model: string;
    baseUrl: string | null;
    fallbackModels: string[];
  };

  constructor(config: {
    provider: string;
    apiKey: string;
    model: string;
    baseUrl: string | null;
    fallbackModels: string[];
  }) {
    this.config = config;
  }

  async generate(messages: Array<{ role: string; content: string }>): Promise<string> {
    const { provider, apiKey, model, baseUrl, fallbackModels } = this.config;
    const models = [model, ...fallbackModels].filter((m, i, arr) => m && arr.indexOf(m) === i);

    let lastError: Error | null = null;
    for (const m of models) {
      try {
        if (provider === 'gemini') {
          return await this.generateGemini(m, messages, apiKey, baseUrl);
        }
        if (provider === 'openai' || provider === 'openai_compatible' || provider === 'mistral') {
          const apiBase = provider === 'mistral' && !baseUrl ? 'https://api.mistral.ai/v1' : baseUrl;
          return await this.generateOpenAI(m, messages, apiKey, apiBase);
        }
        if (provider === 'anthropic') {
          return await this.generateAnthropic(m, messages, apiKey);
        }
        throw new Error(`Unsupported provider: ${provider}`);
      } catch (err: any) {
        lastError = err;
        if (!isRetryableError(err.message)) throw err;
      }
    }
    throw lastError || new Error('LLM generation failed');
  }

  async generateStream(
    messages: Array<{ role: string; content: string }>
  ): Promise<AsyncGenerator<StreamingChunk>> {
    const { provider, apiKey, model, baseUrl, fallbackModels } = this.config;
    const models = [model, ...fallbackModels].filter((m, i, arr) => m && arr.indexOf(m) === i);

    for (const m of models) {
      try {
        if (provider === 'gemini') {
          return this.generateGeminiStream(m, messages, apiKey, baseUrl);
        }
        if (provider === 'openai' || provider === 'openai_compatible' || provider === 'mistral') {
          const apiBase = provider === 'mistral' && !baseUrl ? 'https://api.mistral.ai/v1' : baseUrl;
          return this.generateOpenAIStream(m, messages, apiKey, apiBase);
        }
        throw new Error(`Unsupported provider for streaming: ${provider}`);
      } catch (err: any) {
        if (!isRetryableError(err.message)) throw err;
      }
    }
    throw new Error('All models failed for streaming');
  }

  private async generateGemini(
    model: string,
    messages: Array<{ role: string; content: string }>,
    apiKey: string,
    baseUrl: string | null
  ): Promise<string> {
    const genAI = new GoogleGenerativeAI(apiKey);
    const geminiModel = genAI.getGenerativeModel({ model });
    const contents = messages.map(m => ({
      role: m.role === 'system' ? 'user' : (m.role === 'assistant' ? 'model' : m.role),
      parts: [{ text: m.content }],
    }));
    const result = await geminiModel.generateContent({ contents });
    return cleanLlmText(result.response.text());
  }

  private async generateOpenAI(
    model: string,
    messages: Array<{ role: string; content: string }>,
    apiKey: string,
    baseUrl: string | null
  ): Promise<string> {
    const client = new OpenAI({ apiKey, baseURL: baseUrl || undefined });
    const resp = await client.chat.completions.create({
      model,
      messages: messages as any,
      temperature: 0.2,
    });
    const content = resp.choices[0]?.message?.content || '';
    return cleanLlmText(content);
  }

  private async generateAnthropic(
    model: string,
    messages: Array<{ role: string; content: string }>,
    apiKey: string
  ): Promise<string> {
    const systemContent = messages.find(m => m.role === 'system')?.content || '';
    const userMessages = messages.filter(m => m.role !== 'system').map(m => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    }));
    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model,
        max_tokens: 1024,
        messages: userMessages,
        ...(systemContent ? { system: systemContent } : {}),
        temperature: 0.2,
      }),
    });
    if (!resp.ok) throw new Error(`Anthropic API error: ${await resp.text()}`);
    const data = await resp.json() as any;
    return cleanLlmText(data.content[0]?.text || '');
  }

  private async *generateGeminiStream(
    model: string,
    messages: Array<{ role: string; content: string }>,
    apiKey: string,
    baseUrl: string | null
  ): AsyncGenerator<StreamingChunk> {
    const genAI = new GoogleGenerativeAI(apiKey);
    const geminiModel = genAI.getGenerativeModel({ model });
    const contents = messages.map(m => ({
      role: m.role === 'system' ? 'user' : (m.role === 'assistant' ? 'model' : m.role),
      parts: [{ text: m.content }],
    }));
    const result = await geminiModel.generateContentStream({ contents });
    for await (const chunk of result.stream) {
      const text = chunk.text();
      if (text) {
        yield { text, done: false };
      }
    }
    yield { text: '', done: true };
  }

  private async *generateOpenAIStream(
    model: string,
    messages: Array<{ role: string; content: string }>,
    apiKey: string,
    baseUrl: string | null
  ): AsyncGenerator<StreamingChunk> {
    const url = `${(baseUrl || 'https://api.openai.com/v1').replace(/\/$/, '')}/chat/completions`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model, messages, temperature: 0.2, stream: true }),
      signal: AbortSignal.timeout(120000),
    });

    if (!response.ok) {
      const errText = await response.text();
      yield { text: '', done: true, error: `LLM API error ${response.status}: ${errText}` };
      return;
    }

    // Raw SSE line-by-line parsing — same approach as Python httpx aiter_lines()
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const dataStr = trimmed.slice(6).trim();
        if (dataStr === '[DONE]') {
          yield { text: '', done: true };
          return;
        }
        if (!dataStr) continue;
        try {
          const data = JSON.parse(dataStr);
          const content: string = data?.choices?.[0]?.delta?.content ?? '';
          if (content) yield { text: content, done: false };
        } catch { /* skip malformed chunk */ }
      }
    }
    yield { text: '', done: true };
  }
}

function isRetryableError(message: string): boolean {
  const markers = ['429', '503', 'RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'timeout', 'high demand'];
  return markers.some(m => message.includes(m));
}
