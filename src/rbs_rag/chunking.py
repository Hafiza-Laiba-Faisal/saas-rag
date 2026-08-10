from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from .models import Chunk, LoadedDocument

log = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")

# ── Boilerplate / junk detection ──────────────────────────────────────────────
# These heuristics drop content that pollutes retrieval top-k slots: cookie
# consent banners, legal boilerplate, language-switcher nav, bare "Source:"
# header lines, and tiny fragments. Filtering happens BEFORE embedding so junk
# never reaches the vector index.

_SOURCE_LINE_RE = re.compile(r"^\s*(?:Source|URL|Link|Reference)\s*:\s*\S+.*$", re.IGNORECASE)

_CONSENT_MARKERS = (
    "cookie", "accept", "consent", "preferences", "gdpr", "personal data",
    "analytics", "necessary cookie", "privacy", "privacy policy",
)
_LEGAL_MARKERS = (
    "privacy policy", "terms of use", "terms and conditions", "all rights reserved",
    "cookie policy", "\u00a9", "copyright", "legal notice", "imprint",
)
_LANG_MARKERS = (
    "language switcher", "change language", "select your language",
    "choose language", "select language", "switch language",
)
# 2-letter ISO codes must match as WHOLE WORDS only — a bare substring match
# would flag "it" inside "site", "en" inside "when", "de" inside "desk", etc.
_LANG_CODES = ("it", "en", "fr", "de", "es")
_LANG_NAME_WORDS = ("deutsch", "english", "fran\u00e7ais", "italiano", "espa\u00f1ol")
_LANG_CODE_RES = tuple(re.compile(rf"(?<![a-z]){code}(?![a-z])") for code in _LANG_CODES)


def _normalize_text(text: str) -> str:
    """Canonical signature for duplicate detection (case/punctuation-insensitive)."""
    return re.sub(r"[\W_]+", "", text.lower())


def _boilerplate_reason(text: str) -> str | None:
    """Return a reason string if the text looks like junk, else None."""
    stripped = text.strip()
    if not stripped:
        return "empty"
    if len(stripped) < 25:
        return "tiny"

    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if lines and all(_SOURCE_LINE_RE.match(ln) for ln in lines):
        return "source_header"

    words = stripped.split()
    word_count = len(words)
    lower = f" {stripped.lower()} "

    # FAQ guard: question-form sentences are legitimate informational content
    # ("What are cookies? Cookies are small files..."), not banners. Never drop
    # real explainer text just because it mentions consent/legal keywords.
    if "?" in stripped:
        return None

    # Cookie/consent banner: short text with several consent markers.
    consent_hits = [m for m in _CONSENT_MARKERS if m in lower]
    if word_count <= 80 and "cookie" in lower and len(consent_hits) >= 2:
        return "cookie_banner"

    # Legal boilerplate: short text with several legal markers.
    legal_hits = [m for m in _LEGAL_MARKERS if m in lower]
    if word_count <= 80 and len(legal_hits) >= 2:
        return "legal_boilerplate"

    # Language-switcher nav junk: needs an explicit switcher marker AND at least
    # two language mentions (codes as whole words, or full language names).
    lang_hits = [m for m in _LANG_MARKERS if m in lower]
    name_hits = [w for w in _LANG_NAME_WORDS if w in lower]
    code_hits = [c for c, rx in zip(_LANG_CODES, _LANG_CODE_RES) if rx.search(lower)]
    if word_count <= 60 and lang_hits and len(name_hits + code_hits) >= 2:
        return "language_switcher"

    return None


class Chunker(Protocol):
    def chunk(self, document: LoadedDocument, tenant_id: str, knowledge_base_id: str) -> list[Chunk]:
        ...


@dataclass(slots=True)
class HierarchicalChunker:
    max_tokens: int = 320
    overlap_tokens: int = 48
    filter_boilerplate: bool = True
    dedupe_within_document: bool = True
    stats: dict = field(default_factory=dict)

    def chunk(self, document: LoadedDocument, tenant_id: str, knowledge_base_id: str) -> list[Chunk]:
        self.stats.clear()
        self.stats.setdefault("filtered", 0)
        self.stats.setdefault("deduped", 0)
        chunks: list[Chunk] = []
        ordinal = 0
        seen: set[str] = set()
        for section, text in _split_sections(document.text):
            for piece in self._split_to_token_windows(text):
                if not piece.strip():
                    continue
                if self.filter_boilerplate:
                    reason = _boilerplate_reason(piece)
                    if reason:
                        self.stats["filtered"] += 1
                        continue
                if self.dedupe_within_document:
                    sig = _normalize_text(piece)
                    if sig in seen:
                        self.stats["deduped"] += 1
                        continue
                    seen.add(sig)
                metadata = dict(document.metadata)
                metadata.update(
                    {
                        "tenant_id": tenant_id,
                        "knowledge_base_id": knowledge_base_id,
                        "document_id": document.document_id,
                        "document_name": document.name,
                        "document_type": document.document_type,
                        "section": section,
                        "chunk_ordinal": ordinal,
                    }
                )
                chunk_id = hashlib.sha1(f"{document.document_id}:{ordinal}:{piece}".encode("utf-8")).hexdigest()
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        text=piece,
                        metadata=metadata,
                        embedding=[],
                        ordinal=ordinal,
                    )
                )
                ordinal += 1
        return chunks

    def _split_to_token_windows(self, text: str) -> list[str]:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n|\r?\n", text) if paragraph.strip()]
        # Filter boilerplate/junk at the PARAGRAPH level so good content next to a
        # cookie banner is never dragged down with it into a shared window.
        if self.filter_boilerplate:
            kept_paragraphs = []
            for paragraph in paragraphs:
                if _boilerplate_reason(paragraph):
                    self.stats.setdefault("filtered", 0)
                    self.stats["filtered"] += 1
                    continue
                kept_paragraphs.append(paragraph)
            paragraphs = kept_paragraphs

        windows: list[str] = []
        current: list[str] = []
        for paragraph in paragraphs:
            words = paragraph.split()
            if len(words) > self.max_tokens:
                if current:
                    windows.append(" ".join(current))
                    current = []
                windows.extend(self._window_words(words))
                continue
            if len(current) + len(words) <= self.max_tokens:
                current.extend(words)
            else:
                if current:
                    windows.append(" ".join(current))
                overlap = current[-self.overlap_tokens :] if self.overlap_tokens > 0 else []
                current = overlap + words
                if len(current) > self.max_tokens:
                    windows.extend(self._window_words(current))
                    current = []
        if current:
            windows.append(" ".join(current))
        return windows

    def _window_words(self, words: list[str]) -> list[str]:
        step = max(self.max_tokens - self.overlap_tokens, 1)
        output = []
        for start in range(0, len(words), step):
            window = words[start : start + self.max_tokens]
            if window:
                output.append(" ".join(window))
            if start + self.max_tokens >= len(words):
                break
        return output


@dataclass
class SemanticChunker:
    chunker: HierarchicalChunker
    similarity_threshold: float = 0.75

    def chunk(self, document: LoadedDocument, tenant_id: str, knowledge_base_id: str) -> list[Chunk]:
        base_chunks = self.chunker.chunk(document, tenant_id, knowledge_base_id)
        if len(base_chunks) <= 1:
            return base_chunks
        try:
            return self._merge_semantic(base_chunks)
        except Exception as exc:
            log.warning("Semantic chunking failed (%s), returning hierarchical chunks", exc)
            return base_chunks

    def _merge_semantic(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return chunks

        try:
            from fastembed import TextEmbedding
            model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir=".fastembed_cache")
        except ImportError:
            return chunks

        texts = [chunk.text for chunk in chunks]
        embeddings = list(model.embed(texts))
        embeddings = [e.tolist() if hasattr(e, "tolist") else e for e in embeddings]

        merged: list[Chunk] = []
        current_texts = [chunks[0].text]
        current_meta = [chunks[0].metadata]
        current_emb = [embeddings[0]]

        for i in range(1, len(chunks)):
            sim = self._cosine_similarity(embeddings[i - 1], embeddings[i])
            if sim >= self.similarity_threshold:
                current_texts.append(chunks[i].text)
                current_meta.append(chunks[i].metadata)
                current_emb.append(embeddings[i])
            else:
                merged.append(self._make_merged_chunk(chunks[i - 1], current_texts, current_meta, current_emb))
                current_texts = [chunks[i].text]
                current_meta = [chunks[i].metadata]
                current_emb = [embeddings[i]]

        if current_texts:
            merged.append(self._make_merged_chunk(chunks[-1], current_texts, current_meta, current_emb))

        return merged

    def _make_merged_chunk(self, base: Chunk, texts: list[str], metadatas: list[dict], embeddings: list[list[float]]) -> Chunk:
        import numpy as np
        merged_text = " ".join(texts)
        avg_embedding = np.mean(embeddings, axis=0).tolist() if len(embeddings) > 1 else embeddings[0]
        chunk_id = hashlib.sha1(f"{base.document_id}:sem:{base.ordinal}:{merged_text[:80]}".encode("utf-8")).hexdigest()
        return Chunk(
            chunk_id=chunk_id,
            document_id=base.document_id,
            text=merged_text,
            metadata=metadatas[0],
            embedding=avg_embedding,
            ordinal=base.ordinal,
        )

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


def create_chunker(chunking_config) -> Chunker:
    base = HierarchicalChunker(max_tokens=chunking_config.max_tokens, overlap_tokens=chunking_config.overlap_tokens)
    if chunking_config.semantic_chunking:
        return SemanticChunker(chunker=base, similarity_threshold=chunking_config.semantic_similarity_threshold)
    return base


def _split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = "General"
    current_lines: list[str] = []
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
                current_lines = []
            current_title = heading.group(2).strip()
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    if not sections and text.strip():
        sections.append(("General", text.strip()))
    return sections
