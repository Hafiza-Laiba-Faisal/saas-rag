from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .text import l2_normalize, tokenize

log = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class SparseEmbeddingProvider(Protocol):
    def embed_sparse(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(slots=True)
class HashEmbeddingProvider:
    dimensions: int = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return l2_normalize(vector)


class FastEmbedProvider:
    def __init__(self, model: str, dimensions: int):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("FastEmbed requires 'fastembed'. Install with: pip install -e .[local-ml]") from exc
        self._model = TextEmbedding(model_name=model, cache_dir=".fastembed_cache")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [embedding.tolist() for embedding in self._model.embed(texts)]


class BGEProvider:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", dimensions: int = 384):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("FastEmbed requires 'fastembed'. Install with: pip install -e .[local-ml]") from exc
        self._model = TextEmbedding(model_name=model, cache_dir=".fastembed_cache")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [embedding.tolist() for embedding in self._model.embed(texts)]


class BGEM3Provider:
    def __init__(self, model: str = "BAAI/bge-m3", dimensions: int = 1024):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("FastEmbed requires 'fastembed'. Install with: pip install -e .[local-ml]") from exc
        self._model = TextEmbedding(model_name=model, cache_dir=".fastembed_cache")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [embedding.tolist() for embedding in self._model.embed(texts)]

    def embed_sparse(self, texts: list[str]) -> list[list[float]]:
        try:
            embeddings = list(self._model.embed(texts))
            return [e.tolist() for e in embeddings]
        except Exception:
            log.warning("Sparse embedding not supported by this fastembed model, returning dense vectors")
            return self.embed(texts)


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimensions: int = 1536):
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ValueError("OpenAI API key is required for OpenAI embeddings.")
        url = "https://api.openai.com/v1/embeddings"
        payload = {"input": texts, "model": self.model}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sorted_data = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in sorted_data]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI embedding request failed: {body}") from exc


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, api_key: str, base_url: str | None = None, model: str = "text-embedding-3-small", dimensions: int = 1536):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ValueError("API key is required for OpenAI-compatible embeddings.")
        url = f"{self.base_url}/embeddings"
        payload = {"input": texts, "model": self.model}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sorted_data = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in sorted_data]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible embedding request failed: {body}") from exc


class GeminiEmbeddingProvider:
    def __init__(self, api_key: str, model: str = "text-embedding-004", dimensions: int = 768):
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ValueError("Gemini API key is required.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents?key={self.api_key}"
        payload = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": text}]}} for text in texts]}
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [item["values"] for item in data["embeddings"]]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini embedding request failed: {body}") from exc


def create_embedding_provider(
    provider: str,
    dimensions: int,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> EmbeddingProvider:
    if provider == "hash":
        return HashEmbeddingProvider(dimensions=dimensions)
    if provider == "fastembed":
        return FastEmbedProvider(model=model, dimensions=dimensions)
    if provider in ("bge", "bge_small"):
        return BGEProvider(model=model or "BAAI/bge-small-en-v1.5", dimensions=dimensions)
    if provider in ("bge_m3", "bge-m3"):
        return BGEM3Provider(model=model or "BAAI/bge-m3", dimensions=dimensions or 1024)
    if provider in {"openai", "openai_compatible", "custom"}:
        return OpenAICompatibleEmbeddingProvider(api_key=api_key or "", base_url=base_url, model=model, dimensions=dimensions)
    if provider == "gemini":
        return GeminiEmbeddingProvider(api_key=api_key or "", model=model, dimensions=dimensions)
    raise ValueError(f"Unsupported embedding provider '{provider}'.")


def create_sparse_provider(
    provider: str,
    dimensions: int,
    model: str,
) -> SparseEmbeddingProvider | None:
    if provider in ("bge_m3", "bge-m3"):
        return BGEM3Provider(model=model or "BAAI/bge-m3", dimensions=dimensions or 1024)
    return None
