from __future__ import annotations

import asyncio
import functools
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    from qdrant_client import QdrantClient as _QdrantClient
    from qdrant_client.http import models as m

    _HAS_QDRANT = True
except ImportError:
    _QdrantClient = None  # type: ignore[assignment]
    m = None  # type: ignore[assignment]
    _HAS_QDRANT = False

from .config import QdrantConfig
from .models import Chunk

log = logging.getLogger(__name__)

_KNOWN_PAYLOAD_FIELDS = frozenset({"chunk_id", "document_id", "text", "ordinal"})


@dataclass(slots=True)
class QdrantVectorStore:
    config: QdrantConfig
    _client: Any = field(default=None, repr=False)
    _initialized: bool = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def client(self) -> Any:
        return self._client

    async def initialize(self):
        if self._initialized:
            return
        if not _HAS_QDRANT:
            log.warning("Qdrant not available; vector ops will be no-ops")
            return
        try:
            url = f"{'https' if self.config.https else 'http'}://{self.config.host}:{self.config.port}"
            kwargs: dict[str, Any] = {"location": url, "prefer_grpc": self.config.prefer_grpc}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._client = _QdrantClient(**kwargs)
            await asyncio.to_thread(self._client.get_collections)
            log.info("Qdrant connected at %s", url)
            self._initialized = True
        except Exception as exc:
            log.warning("Qdrant unavailable (%s); vector ops will be no-ops", exc)

    async def ensure_collection(self, collection: str, vector_size: int = 384):
        if not self._client:
            return
        try:
            await asyncio.to_thread(self._client.get_collection, collection)
        except Exception:
            create = functools.partial(
                self._client.create_collection,
                collection,
                vectors_config=m.VectorParams(size=vector_size, distance=m.Distance.COSINE),
                optimizers_config=m.OptimizersConfigDiff(default_segment_number=2),
                replication_factor=self.config.collection_config.get("replication_factor", 1),
            )
            await asyncio.to_thread(create)
            log.info("Created Qdrant collection '%s'", collection)

    async def upsert_chunks(self, collection: str, chunks: list[Chunk], batch_size: int = 64):
        if not self._client:
            return
        points = []
        for chunk in chunks:
            payload: dict[str, Any] = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "ordinal": chunk.ordinal,
            }
            if chunk.metadata:
                payload.update(chunk.metadata)
            if "tenant_id" not in payload and chunk.metadata.get("tenant_id"):
                payload["tenant_id"] = chunk.metadata["tenant_id"]
            point_id = _make_point_id(chunk.chunk_id)
            points.append(m.PointStruct(id=point_id, vector=chunk.embedding, payload=payload))
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            upsert = functools.partial(self._client.upsert, collection, points=batch)
            await asyncio.to_thread(upsert)

    async def delete_document_chunks(self, collection: str, document_id: str):
        if not self._client:
            return
        delete = functools.partial(
            self._client.delete,
            collection,
            points_selector=m.Filter(
                must=[m.FieldCondition(key="document_id", match=m.MatchValue(value=document_id))]
            ),
        )
        await asyncio.to_thread(delete)

    async def delete_chunks(self, collection: str, chunk_ids: list[str]):
        if not self._client:
            return
        delete = functools.partial(
            self._client.delete, collection, points_selector=m.PointIdsList(points=chunk_ids)
        )
        await asyncio.to_thread(delete)

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 20,
        score_threshold: float | None = None,
        filters: dict[str, str] | None = None,
    ) -> list[Chunk]:
        if not self._client:
            return []
        query_filter = _build_filter(filters)
        result = self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        return [_point_to_chunk(p) for p in result.points]

    def search_batch(
        self,
        collection: str,
        query_vectors: list[list[float]],
        top_k: int = 20,
        filters: dict[str, str] | None = None,
    ) -> list[list[Chunk]]:
        if not self._client:
            return [[] for _ in query_vectors]
        query_filter = _build_filter(filters)
        requests = [m.QueryRequest(vector=qv, limit=top_k, filter=query_filter) for qv in query_vectors]
        results = self._client.query_batch_points(
            collection_name=collection,
            requests=requests,
        )
        return [[_point_to_chunk(p) for p in batch.points] for batch in results]

    async def scroll_all_chunks(self, collection: str, limit: int = 100) -> list[Chunk]:
        if not self._client:
            return []
        scroll = functools.partial(self._client.scroll, collection, limit=limit)
        results, _ = await asyncio.to_thread(scroll)
        return [_point_to_chunk(r) for r in results]

    async def count_chunks(self, collection: str) -> int:
        if not self._client:
            return 0
        result = await asyncio.to_thread(self._client.count, collection)
        return result.count

    async def delete_collection(self, collection: str):
        if not self._client:
            return
        await asyncio.to_thread(self._client.delete_collection, collection)

    async def close(self):
        if self._client:
            await asyncio.to_thread(self._client.close)
            self._client = None
            self._initialized = False


def _make_point_id(chunk_id: str):
    try:
        return uuid.UUID(chunk_id)
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)


def _build_filter(filters: dict[str, str] | None):
    if not filters:
        return None
    must = []
    for key, value in filters.items():
        must.append(
            m.FieldCondition(
                key=key,
                match=m.MatchValue(value=value),
            )
        )
    return m.Filter(must=must)


def _point_to_chunk(point: Any) -> Chunk:
    payload = point.payload or {}
    metadata = {}
    for k, v in payload.items():
        if k not in _KNOWN_PAYLOAD_FIELDS:
            metadata[k] = v
    score = getattr(point, "score", 0.0)
    metadata["_score"] = score
    vector = point.vector if isinstance(point.vector, list) else (point.vector or [])
    chunk_id = payload.get("chunk_id")
    if not chunk_id:
        pid = point.id
        chunk_id = str(pid) if not isinstance(pid, str) else pid
    return Chunk(
        chunk_id=chunk_id,
        document_id=payload.get("document_id", ""),
        text=payload.get("text", ""),
        ordinal=payload.get("ordinal", 0),
        metadata=metadata,
        embedding=vector,
    )
