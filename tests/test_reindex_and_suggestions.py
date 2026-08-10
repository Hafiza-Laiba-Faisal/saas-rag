import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rbs_rag.chunking import HierarchicalChunker
from rbs_rag.config import AppConfig, ChunkingConfig, EmbeddingConfig, RetrievalConfig, StorageConfig, LLMSettings
from rbs_rag.engine import RagEngine
from rbs_rag.evaluation import (
    EvaluationStore,
    _generate_with_retry,
    _is_rate_limited,
    run_evaluation,
    suggest_improvements,
)
from rbs_rag.models import LoadedDocument
from rbs_rag.vector_store import QdrantVectorStore


def _make_config(root: Path, tenant_id: str = "t1", max_tokens: int = 320) -> AppConfig:
    return AppConfig(
        tenant_id=tenant_id,
        default_kb="default",
        session_memory_limit=8,
        chat_retention_days=30,
        storage=StorageConfig(provider="sqlite", path=str(root / f"{tenant_id}.db")),
        embeddings=EmbeddingConfig(provider="hash", model="hash-384", dimensions=384),
        retrieval=RetrievalConfig(top_k=20, rerank_top_k=8, final_context_k=5, dense_weight=0.55, sparse_weight=0.45),
        chunking=ChunkingConfig(max_tokens=max_tokens, overlap_tokens=24),
        system_prompt=None,
        llm=LLMSettings(provider="openai_compatible", api_key="", model="x"),
    )


class RateLimitHelpersTests(unittest.TestCase):
    def test_is_rate_limited_detects_429(self):
        self.assertTrue(_is_rate_limited(RuntimeError("LLM API request failed with HTTP 429: Too Many Requests")))
        self.assertTrue(_is_rate_limited(RuntimeError("rate limit exceeded")))
        self.assertTrue(_is_rate_limited(RuntimeError("HTTP 503 service unavailable")))
        self.assertFalse(_is_rate_limited(RuntimeError("HTTP 400 bad request")))

    def test_generate_with_retry_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky(messages):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("HTTP 429 Too Many Requests")
            return "ok"

        with patch("time.sleep", return_value=None):
            result = _generate_with_retry(MagicMock(generate=flaky), [])
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    def test_generate_with_retry_gives_up_on_persistent_429(self):
        def always_fail(messages):
            raise RuntimeError("HTTP 429 Too Many Requests")

        with patch("time.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                _generate_with_retry(MagicMock(generate=always_fail), [], attempts=3)

    def test_generate_with_retry_does_not_retry_non_transient(self):
        def fail(messages):
            raise RuntimeError("HTTP 400 bad request")

        with patch("time.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                _generate_with_retry(MagicMock(generate=fail), [])


class ReindexTests(unittest.TestCase):
    def _write_docs(self, docs_dir: Path):
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "a.md").write_text(
            "# Hotel\n\nThe hotel offers coworking rooms with fiber Wi-Fi and a rooftop bar.\n",
            encoding="utf-8",
        )
        (docs_dir / "b.md").write_text(
            "# Breakfast\n\nBreakfast is served from 7 AM to 10:30 AM in the garden.\n",
            encoding="utf-8",
        )

    def test_reindex_all_rechunks_with_current_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            self._write_docs(docs_dir)
            engine = RagEngine(_make_config(root, max_tokens=320), root=root)
            engine.vector_store._initialized = False  # no Qdrant in tests

            import asyncio
            summary = asyncio.run(engine.reindex_all(docs_dir))

            self.assertEqual(summary.documents, 2)
            self.assertGreater(summary.chunks, 0)
            # Both docs are in the store now.
            docs = engine.store.list_documents("t1", "default")
            self.assertEqual(len(docs), 2)

            # Re-running reindex drops old chunks and rebuilds identically.
            summary2 = asyncio.run(engine.reindex_all(docs_dir))
            self.assertEqual(summary2.chunks, summary.chunks)

    def test_reindex_aborts_when_no_files_present(self):
        # DATA SAFETY: an empty docs dir must NOT wipe the existing index.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "keep.md").write_text("# Keep\n\nImportant content that must survive.\n", encoding="utf-8")
            engine = RagEngine(_make_config(root), root=root)
            engine.vector_store._initialized = False

            import asyncio
            asyncio.run(engine.reindex_all(docs_dir))
            self.assertEqual(engine.store.count_documents("t1", "default"), 1)

            # Remove the only file, then re-index — must abort, not wipe.
            (docs_dir / "keep.md").unlink()
            summary = asyncio.run(engine.reindex_all(docs_dir))
            self.assertEqual(summary.documents, 0)
            self.assertTrue(summary.errors)
            # Existing document is still intact.
            self.assertEqual(engine.store.count_documents("t1", "default"), 1)

    def test_reindex_after_config_change_uses_new_chunk_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs_dir = root / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "big.md").write_text(
                "# Content\n\n" + ("The hotel spa offers massages and a sauna. " * 120) + "\n",
                encoding="utf-8",
            )
            engine = RagEngine(_make_config(root, max_tokens=320), root=root)
            engine.vector_store._initialized = False

            import asyncio
            s1 = asyncio.run(engine.reindex_all(docs_dir))
            chunks1 = engine.store.list_chunks("t1", "default")
            max_words1 = max(len(c.text.split()) for c in chunks1)

            # Simulate admin raising chunk size, then re-index.
            engine.config.chunking = ChunkingConfig(max_tokens=640, overlap_tokens=48)
            s2 = asyncio.run(engine.reindex_all(docs_dir))
            chunks2 = engine.store.list_chunks("t1", "default")
            max_words2 = max(len(c.text.split()) for c in chunks2)

            self.assertEqual(s2.documents, 1)
            # Larger chunks mean fewer chunks and larger max window.
            self.assertLessEqual(len(chunks2), len(chunks1))
            self.assertGreater(max_words2, max_words1)


class EnsureCollectionDimensionsTests(unittest.TestCase):
    def test_ensure_collection_dimensions_never_deletes_shared_collection(self):
        # The "rag_chunks" collection is SHARED across tenants — a dimension
        # mismatch must warn, never delete (that would wipe other tenants).
        client = MagicMock()
        info = MagicMock()
        params = MagicMock()
        vectors = MagicMock()
        vectors.size = 384
        params.vectors = vectors
        info.config.params = params
        client.get_collection.return_value = info

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        store._client = client
        store.config = MagicMock()

        import asyncio
        from unittest.mock import AsyncMock
        with patch.object(QdrantVectorStore, "ensure_collection", new=AsyncMock()) as ensure:
            asyncio.run(store.ensure_collection_dimensions("rag_chunks", 1536))
            client.delete_collection.assert_not_called()
            ensure.assert_called_once_with("rag_chunks", 1536)

    def test_delete_tenant_chunks_filters_by_tenant(self):
        import asyncio
        client = MagicMock()
        store = QdrantVectorStore.__new__(QdrantVectorStore)
        store._client = client
        store.config = MagicMock()

        asyncio.run(store.delete_tenant_chunks("rag_chunks", "tenant-a"))
        # The delete must carry a tenant_id filter so other tenants are untouched.
        _, kwargs = client.delete.call_args
        selector = kwargs["points_selector"]
        conditions = selector.must
        self.assertTrue(any(c.key == "tenant_id" and c.match.value == "tenant-a" for c in conditions))


class SuggestImprovementsTests(unittest.TestCase):
    def test_suggests_kb_junk_when_duplicates_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            engine = MagicMock()
            engine.store.list_chunks.return_value = [
                MagicMock(text="same content here", document_id="d1"),
                MagicMock(text="same content here", document_id="d2"),
            ]
            engine.store.list_documents.return_value = []
            engine.config.embeddings.provider = "hash"
            engine.config.chunking.max_tokens = 320

            out = suggest_improvements(engine, "t1", store)
            ids = [s["id"] for s in out["suggestions"]]
            self.assertIn("kb_junk", ids)
            # duplicate_pct = #duplicate groups / total chunks = 1/2
            self.assertEqual(out["quality"]["duplicate_pct"], 50.0)

    def test_suggests_semantic_retrieval_on_low_hit_rate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            case = store.add_case("t1", "Where is the pool?")
            run_id = store.create_run("t1", {})
            store.add_result(run_id, {"case_id": case["case_id"], "question": "Where is the pool?",
                                      "retrieval_hit": False, "retrieved_chunks": [], "generated_answer": "",
                                      "faithfulness_score": 0.0, "relevancy_score": 0.0,
                                      "failure_type": "retrieval", "evaluation_reason": "miss"})
            store.update_run(run_id, {"status": "completed", "total_cases": 1, "passed_cases": 0,
                                      "retrieval_hit_rate": 0.0, "faithfulness_score": 0.0,
                                      "relevancy_score": 0.0, "overall_score": 0.0})

            engine = MagicMock()
            engine.store.list_chunks.return_value = []
            engine.store.list_documents.return_value = []
            engine.config.embeddings.provider = "hash"
            engine.config.chunking.max_tokens = 320

            out = suggest_improvements(engine, "t1", store)
            ids = [s["id"] for s in out["suggestions"]]
            self.assertIn("semantic_retrieval", ids)
            sem = next(s for s in out["suggestions"] if s["id"] == "semantic_retrieval")
            self.assertEqual(sem["config_change"]["fields"]["embedding_provider"], "openai")

    def test_suggests_rate_limited_when_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            case = store.add_case("t1", "Q?")
            run_id = store.create_run("t1", {})
            store.add_result(run_id, {"case_id": case["case_id"], "question": "Q?",
                                      "retrieval_hit": False, "retrieved_chunks": [], "generated_answer": "",
                                      "faithfulness_score": 0.0, "relevancy_score": 0.0,
                                      "failure_type": "error", "evaluation_reason": "HTTP 429"})
            store.update_run(run_id, {"status": "completed", "total_cases": 1, "passed_cases": 0,
                                      "retrieval_hit_rate": 0.0, "faithfulness_score": 0.0,
                                      "relevancy_score": 0.0, "overall_score": 0.0})
            engine = MagicMock()
            engine.store.list_chunks.return_value = []
            engine.store.list_documents.return_value = []
            engine.config.embeddings.provider = "hash"
            engine.config.chunking.max_tokens = 320

            out = suggest_improvements(engine, "t1", store)
            ids = [s["id"] for s in out["suggestions"]]
            self.assertIn("rate_limited", ids)


if __name__ == "__main__":
    unittest.main()
