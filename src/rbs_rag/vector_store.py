from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import QdrantConfig
from .models import Chunk

log = logging.getLogger(__name__)


@dataclass
class QdrantVectorStore:
    config: QdrantConfig
    _client: Any = field(default=None, repr=False)
    _initialized: bool = False

    async def initialize(self):
        if self._initialized:
            return
        try:
            from qdrant_client import QdrantClient as _QdrantClient
            from qdrant_client.http import models as m
            self._m = m
            url = f"{'https' if self.config.https else 'http'}://{self.config.host}:{self.config.port}"
            kwargs = {"location": url, "prefer_grpc": self.config.prefer_grpc}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            self._client = _QdrantClient(**kwargs)
            self._client.get_collections()
            log.info("Qdrant connected at %s", url)
            self._initialized = True
        except Exception as exc:
            log.warning("Qdrant unavailable (%s); vector ops will be no-ops", exc)

    async def ensure_collection(self, collection: str, vector_size: int = 384):
        if not self._client:
            return
        try:
            self._client.get_collection(collection)
        except Exception:
            self._client.create_collection(
                collection,
                vectors_config=self._m.VectorParams(size=vector_size, distance=self._m.Distance.COSINE),
                optimizers_config=self._m.OptimizersConfigDiff(default_segment_number=2),
                replication_factor=self.config.collection_config.get("replication_factor", 1),
            )
            log.info("Created Qdrant collection '%s'", collection)

    async def upsert_chunks(self, collection: str, chunks: list[Chunk], batch_size: int = 64):
        if not self._client:
            return
        from qdrant_client.http import models as m
        points = []
        for chunk in chunks:
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "ordinal": chunk.ordinal,
                "metadata_json": json.dumps(chunk.metadata, default=str),
            }
            point_id = uuid.UUID(hex=chunk.chunk_id[:32])
            points.append(m.PointStruct(id=point_id, vector=chunk.embedding, payload=payload))
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self._client.upsert(collection, points=batch)

    async def delete_document_chunks(self, collection: str, document_id: str):
        if not self._client:
            return
        self._client.delete(
            collection,
            points_selector=self._m.Filter(
                must=[self._m.FieldCondition(key="document_id", match=self._m.MatchValue(value=document_id))]
            ),
        )

    async def delete_chunks(self, collection: str, chunk_ids: list[str]):
        if not self._client:
            return
        self._client.delete(collection, points_selector=self._m.PointIdsList(points=chunk_ids))

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
        query_filter = self._build_filter(filters)
        result = self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        return [self._point_to_chunk(p) for p in result.points]

    def search_batch(
        self,
        collection: str,
        query_vectors: list[list[float]],
        top_k: int = 20,
        filters: dict[str, str] | None = None,
    ) -> list[list[Chunk]]:
        if not self._client:
            return [[] for _ in query_vectors]
        query_filter = self._build_filter(filters)
        requests = [
            self._m.QueryRequest(vector=qv, limit=top_k, filter=query_filter)
            for qv in query_vectors
        ]
        results = self._client.query_batch_points(
            collection_name=collection,
            requests=requests,
        )
        return [[self._point_to_chunk(p) for p in batch.points] for batch in results]

    async def scroll_all_chunks(self, collection: str, limit: int = 100) -> list[Chunk]:
        if not self._client:
            return []
        results, _ = self._client.scroll(collection, limit=limit)
        return [self._point_to_chunk(r) for r in results]

    async def count_chunks(self, collection: str) -> int:
        if not self._client:
            return 0
        result = self._client.count(collection)
        return result.count

    async def delete_collection(self, collection: str):
        if not self._client:
            return
        self._client.delete_collection(collection)

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._initialized = False

    def _build_filter(self, filters: dict[str, str] | None):
        if not filters or not self._client:
            return None
        must = []
        for key, value in filters.items():
            must.append(
                self._m.FieldCondition(
                    key=f"metadata_json.{key}",
                    match=self._m.MatchValue(value=value),
                )
            )
        return self._m.Filter(must=must)

    def _point_to_chunk(self, point: Any) -> Chunk:
        payload = point.payload or {}
        metadata = {}
        raw_mj = payload.get("metadata_json")
        if raw_mj:
            try:
                metadata = json.loads(raw_mj)
            except (json.JSONDecodeError, TypeError):
                metadata = {"raw": raw_mj}
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
