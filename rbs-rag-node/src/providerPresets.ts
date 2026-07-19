import fs from 'fs';
import path from 'path';

export type ProviderPreset = {
  id: string;
  name: string;
  models: string[];
  defaultBaseUrl: string;
};

const DEFAULT_PRESETS: ProviderPreset[] = [
  { id: 'gemini', name: 'Google Gemini Cloud', models: ['gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-pro-exp-03-25', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'], defaultBaseUrl: '' },
  { id: 'mistral', name: 'Mistral Cloud', models: ['mistral-small-latest', 'mistral-medium-latest', 'mistral-large-latest', 'open-mistral-nemo', 'codestral-latest'], defaultBaseUrl: 'https://api.mistral.ai/v1' },
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4o', 'gpt-4o-mini-search-preview', 'gpt-4.1', 'gpt-4.1-mini', 'o3-mini', 'o4-mini'], defaultBaseUrl: '' },
  { id: 'nvidia', name: 'NVIDIA NIM Cloud', models: ['meta/llama-3.1-8b-instruct', 'meta/llama-3.1-70b-instruct', 'meta/llama-3.1-405b-instruct', 'mistralai/mistral-nemo-12b-instruct', 'nvidia/llama-3.1-nvip-nvlm-8b'], defaultBaseUrl: 'https://api.nvcf.nvidia.com/v1' },
  { id: 'openrouter', name: 'OpenRouter API', models: ['openai/gpt-4o-mini', 'openai/gpt-4o', 'anthropic/claude-3.5-haiku', 'anthropic/claude-3.5-sonnet', 'google/gemini-2.5-flash-lite', 'meta-llama/llama-3.1-8b-instruct'], defaultBaseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'anthropic', name: 'Anthropic Claude', models: ['claude-3-5-haiku-latest', 'claude-3-5-sonnet-latest', 'claude-opus-4-20250514', 'claude-sonnet-4-20250514'], defaultBaseUrl: '' },
  { id: 'openai_compatible', name: 'OpenAI-Compatible (Ollama/vLLM)', models: ['gpt-4o-mini', 'gpt-4o', 'llama3.1:8b', 'llama3.1:70b', 'mistral-nemo:12b'], defaultBaseUrl: 'http://localhost:11434/v1' },
];

export function loadProviderPresets(rootDir: string): ProviderPreset[] {
  const filePath = path.join(rootDir, 'provider-presets.json');
  if (!fs.existsSync(filePath)) {
    saveProviderPresets(rootDir, DEFAULT_PRESETS);
    return [...DEFAULT_PRESETS];
  }
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw);
  } catch {
    return [...DEFAULT_PRESETS];
  }
}

export function saveProviderPresets(rootDir: string, presets: ProviderPreset[]): void {
  const filePath = path.join(rootDir, 'provider-presets.json');
  fs.writeFileSync(filePath, JSON.stringify(presets, null, 2), 'utf-8');
}
