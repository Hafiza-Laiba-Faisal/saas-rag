from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


Metadata = dict[str, Any]


@dataclass(slots=True)
class LoadedDocument:
    document_id: str
    path: str
    name: str
    document_type: str
    text: str
    metadata: Metadata = field(default_factory=dict)
    ocr_applied: bool = False
    ocr_engine: str | None = None
    page_count: int | None = None


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    metadata: Metadata
    embedding: list[float]
    ordinal: int = 0
    sparse_embedding: list[float] | None = None


@dataclass(slots=True)
class SearchResult:
    chunk: Chunk
    score: float
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rerank_score: float = 0.0


@dataclass(slots=True)
class IngestSummary:
    documents: int = 0
    chunks: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalValidation:
    sufficient: bool
    confidence: str
    reasons: list[str] = field(default_factory=list)
    citation_quality: float = 0.0
    answer_completeness: float = 0.0
    confidence_score: float = 0.0


@dataclass(slots=True)
class Citation:
    index: int
    document_name: str
    section: str | None
    chunk_id: str


@dataclass(slots=True)
class Answer:
    text: str
    citations: list[Citation]
    validation: RetrievalValidation
    contexts: list[SearchResult]
    profile: dict[str, Any] = field(default_factory=dict)
    streaming: bool = False


@dataclass(slots=True)
class OCRMetadata:
    engine: str
    pages: int = 0
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    languages: list[str] = field(default_factory=lambda: ["en"])


@dataclass(slots=True)
class ScrapeMetadata:
    url: str
    title: str = ""
    status_code: int = 200
    content_length: int = 0
    crawl_depth: int = 1
    pages_scraped: int = 1
    processing_time_ms: float = 0.0


@dataclass(slots=True)
class StreamingChunk:
    text: str
    done: bool = False
    error: str | None = None
    citations: list[Citation] | None = None


@dataclass(slots=True)
class HealthStatus:
    status: str = "ok"
    db: str = "connected"
    qdrant: str = "disconnected"
    llm: str = "unknown"
    embeddings: str = "unknown"
    version: str = "1.0.0"
    uptime_seconds: float = 0.0
    total_documents: int = 0
    total_chunks: int = 0
