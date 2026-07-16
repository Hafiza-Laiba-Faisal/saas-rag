from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import AsyncGenerator, Protocol, runtime_checkable

import httpx

import unicodedata

from .models import StreamingChunk

log = logging.getLogger(__name__)

# Strip HTML tags and broken tags like strong>text (missing <)
_HTML_TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9]*[^>]*>')
_BROKEN_TAG_RE = re.compile(r'(?<!<)(strong|em|b|i|p|u|s|span|div|h[1-6]|li|ul|ol|br|hr|a|img|table|tr|td|th)\s*>', re.IGNORECASE)
_OPEN_BROKEN_TAG_RE = re.compile(r'<\s*(strong|em|b|i|p|u|s|span|div|h[1-6]|li|ul|ol|br|hr|a|img|table|tr|td|th)\s*$', re.IGNORECASE)

def _clean_llm_text(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = _HTML_TAG_RE.sub('', text)
    text = _BROKEN_TAG_RE.sub('', text)
    text = _OPEN_BROKEN_TAG_RE.sub(' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


@dataclass(slots=True)
class LLMSettings:
    provider: str | None = None
    api_key: str | None = None
    model: str = "gemini-2.5-flash-lite"
    base_url: str | None = None
    timeout_seconds: int = 120
    fallback_models: list[str] = field(default_factory=list)


@runtime_checkable
class LLMClient(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> str:
        ...


@runtime_checkable
class StreamingLLMClient(Protocol):
    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[StreamingChunk, None]:
        ...


def detect_llm_provider(settings: LLMSettings) -> str:
    if settings.provider:
        return settings.provider
    base_url = (settings.base_url or "").lower()
    api_key = settings.api_key or ""
    model = settings.model.lower()
    if api_key.startswith("AIza") or "generativelanguage.googleapis.com" in base_url or model.startswith("gemini"):
        return "gemini"
    if "anthropic.com" in base_url or model.startswith("claude") or api_key.startswith("sk-ant"):
        return "anthropic"
    return "openai_compatible"


DEFAULT_SYSTEM_PROMPT = (
    "You are a multilingual enterprise knowledge assistant. "
    "Always respond in the same language as the user's question. "
    "Answer only from the supplied context. "
    "If the context is insufficient, state what information is missing rather than guessing. "
    "Cite evidence with bracketed numbers like [1]. "
    "Be concise, professional, and helpful. "
    "Never fabricate URLs, statistics, or facts.\n\n"
    "OUTPUT FORMAT:\n"
    "- Use **bold** for key terms or hotel names.\n"
    "- Use bullet lists for amenities, services, or features.\n"
    "- Never output HTML tags, HTML fragments, or broken tags.\n"
    "- Before responding, remove all HTML, broken tags, and normalize whitespace.\n"
    "- Ensure proper spacing between words."
)

def build_rag_messages(query: str, contexts, session_memory: str = "", system_prompt: str | None = None) -> list[dict[str, str]]:
    context_lines: list[str] = []
    for index, result in enumerate(contexts, start=1):
        metadata = result.chunk.metadata
        document_name = metadata.get("document_name", "unknown document")
        section = metadata.get("section")
        label = f"[{index}] {document_name}"
        if section:
            label += f" / {section}"
        context_lines.append(f"{label}\n{result.chunk.text}")

    memory_block = f"\nSession memory:\n{session_memory}\n" if session_memory else ""
    context_block = "\n\n".join(context_lines) if context_lines else "No retrieved context."
    system = system_prompt or DEFAULT_SYSTEM_PROMPT
    log.info("=== RETRIEVED CONTEXT for query=%r ===\n%s", query, context_block[:2000])
    user = f"{memory_block}\nRetrieved context:\n{context_block}\n\nUser question: {query}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user.strip()}]


class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings):
        if not settings.api_key:
            raise ValueError("LLM API key is required for OpenAI-compatible generation.")
        self.settings = settings

    def generate(self, messages: list[dict[str, str]]) -> str:
        base_url = (self.settings.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        last_error: RuntimeError | None = None
        for model in _unique_models(self.settings.model, self.settings.fallback_models):
            payload = {"model": model, "messages": messages, "temperature": 0.2}
            try:
                headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json", "User-Agent": "OpenAI/Python 1.30.0", "Accept": "application/json"}
                response = _post_json(url, payload, headers=headers, timeout=self.settings.timeout_seconds)
                msg_obj = response["choices"][0]["message"]
                content = msg_obj.get("content") or ""
                reasoning = msg_obj.get("reasoning_content") or ""
                if not content and reasoning:
                    return f"Thinking:\n{reasoning}"
                return _clean_llm_text(content)
            except RuntimeError as exc:
                if not _is_retryable_model_error(exc):
                    raise
                last_error = exc
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected OpenAI-compatible response shape: {response!r}") from exc
        raise last_error or RuntimeError("LLM API request failed.")

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[StreamingChunk, None]:
        base_url = (self.settings.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        for model in _unique_models(self.settings.model, self.settings.fallback_models):
            try:
                async with _get_async_client() as client:
                    async with client.stream(
                        "POST",
                        url,
                        json={"model": model, "messages": messages, "temperature": 0.2, "stream": True},
                        headers={"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"},
                        timeout=self.settings.timeout_seconds,
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                yield StreamingChunk(text="", done=True)
                                return
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                raw = content
                                cleaned = _clean_llm_text(content)
                                if raw != cleaned or "strong" in raw.lower() or "<" in raw:
                                    log.info("=== RAW LLM CHUNK === %r", raw)
                                yield StreamingChunk(text=cleaned, done=False)
                return
            except Exception as exc:
                if not _is_retryable_error(str(exc)):
                    yield StreamingChunk(text="", done=True, error=str(exc))
                    return
                log.warning("Stream attempt with %s failed, retrying: %s", model, exc)
        yield StreamingChunk(text="", done=True, error="All models failed for streaming.")


class GeminiClient:
    def __init__(self, settings: LLMSettings):
        if not settings.api_key:
            raise ValueError("LLM API key is required for Gemini generation.")
        self.settings = settings

    def generate(self, messages: list[dict[str, str]]) -> str:
        base_url = (self.settings.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        contents = []
        for message in messages:
            role = "user" if message["role"] in {"system", "user"} else "model"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        last_error: RuntimeError | None = None
        for model in _unique_models(self.settings.model, self.settings.fallback_models):
            url = f"{base_url}/models/{model}:generateContent?key={self.settings.api_key}"
            try:
                response = _post_json(url, {"contents": contents}, headers={"Content-Type": "application/json"}, timeout=self.settings.timeout_seconds)
                return _clean_llm_text(response["candidates"][0]["content"]["parts"][0]["text"])
            except RuntimeError as exc:
                if not _is_retryable_model_error(exc):
                    raise
                last_error = exc
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected Gemini response shape: {response!r}") from exc
        raise last_error or RuntimeError("LLM API request failed.")

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncGenerator[StreamingChunk, None]:
        base_url = (self.settings.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        contents = []
        for message in messages:
            role = "user" if message["role"] in {"system", "user"} else "model"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        for model in _unique_models(self.settings.model, self.settings.fallback_models):
            try:
                url = f"{base_url}/models/{model}:streamGenerateContent?alt=sse&key={self.settings.api_key}"
                async with _get_async_client() as client:
                    async with client.stream(
                        "POST",
                        url,
                        json={"contents": contents},
                        headers={"Content-Type": "application/json"},
                        timeout=self.settings.timeout_seconds,
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            candidates = data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    text = part.get("text", "")
                                    if text:
                                        raw = text
                                        cleaned = _clean_llm_text(text)
                                        if raw != cleaned or "strong" in raw.lower() or "<" in raw:
                                            log.info("=== RAW GEMINI CHUNK === %r", raw)
                                        yield StreamingChunk(text=cleaned, done=False)
                yield StreamingChunk(text="", done=True)
                return
            except Exception as exc:
                if not _is_retryable_error(str(exc)):
                    yield StreamingChunk(text="", done=True, error=str(exc))
                    return
                log.warning("Gemini stream attempt with %s failed, retrying: %s", model, exc)
        yield StreamingChunk(text="", done=True, error="All models failed.")


class AnthropicClient:
    def __init__(self, settings: LLMSettings):
        if not settings.api_key:
            raise ValueError("LLM API key is required for Anthropic generation.")
        self.settings = settings

    def generate(self, messages: list[dict[str, str]]) -> str:
        base_url = (self.settings.base_url or "https://api.anthropic.com/v1").rstrip("/")
        url = f"{base_url}/messages"
        system_content = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append({"role": msg["role"], "content": msg["content"]})
        last_error: RuntimeError | None = None
        for model in _unique_models(self.settings.model or "claude-3-5-sonnet-20240620", self.settings.fallback_models):
            payload = {"model": model, "max_tokens": 1024, "messages": user_messages, "temperature": 0.2}
            if system_content:
                payload["system"] = system_content
            headers = {"x-api-key": self.settings.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            try:
                response = _post_json(url, payload, headers=headers, timeout=self.settings.timeout_seconds)
                return _clean_llm_text(response["content"][0]["text"])
            except RuntimeError as exc:
                if not _is_retryable_model_error(exc):
                    raise
                last_error = exc
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected Anthropic response shape: {response!r}") from exc
        raise last_error or RuntimeError("Anthropic API request failed.")


def create_llm_client(settings: LLMSettings) -> LLMClient:
    provider = detect_llm_provider(settings)
    if provider == "gemini":
        return GeminiClient(settings)
    if provider == "anthropic":
        return AnthropicClient(settings)
    if provider in {"openai", "openai_compatible", "mistral", "nvidia", "openrouter", "groq", "together", "fireworks", "custom"}:
        return OpenAICompatibleClient(settings)
    raise ValueError(f"Unsupported LLM provider '{provider}'.")


def create_streaming_client(settings: LLMSettings) -> StreamingLLMClient:
    provider = detect_llm_provider(settings)
    client = create_llm_client(settings)
    if isinstance(client, StreamingLLMClient):
        return client
    if isinstance(client, GeminiClient):
        return client
    if isinstance(client, OpenAICompatibleClient):
        return client
    raise ValueError(f"Streaming not supported for provider '{provider}'.")


_shared_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))
    return _shared_client


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    client = _get_client()
    try:
        resp = client.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"LLM API request failed with HTTP {exc.response.status_code}: {exc.response.text}") from exc


def _unique_models(primary: str, fallbacks: list[str]) -> list[str]:
    models: list[str] = []
    for model in [primary] + fallbacks:
        if model and model not in models:
            models.append(model)
    return models


def _is_retryable_model_error(error: RuntimeError) -> bool:
    message = str(error)
    retry_markers = ["HTTP 429", "HTTP 503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "high demand"]
    return any(marker in message for marker in retry_markers)


def _is_retryable_error(message: str) -> bool:
    markers = ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timeout", "Connection refused", "RemoteDisconnected"]
    return any(marker in message for marker in markers)


def _get_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), limits=httpx.Limits(max_keepalive_connections=5, max_connections=10))
