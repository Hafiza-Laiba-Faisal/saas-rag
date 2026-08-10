import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rbs_rag.evaluation import (
    EvaluationStore,
    _document_hit,
    generate_cases,
    kb_quality,
    run_evaluation,
)


class FakeLLMClient:
    """Deterministic LLM stub returning canned responses."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self._responses.pop(0) if self._responses else "{}"


class FakeEngine:
    """Minimal engine stub exposing what evaluation.py uses."""

    def __init__(self, chunks, documents, llm_client=None, config=None):
        class _Store:
            def __init__(self, path, chunks, documents):
                self.path = path
                self._chunks = chunks
                self._documents = documents

            def list_chunks(self, tenant_id, kb):
                return self._chunks

            def list_documents(self, tenant_id, kb):
                return self._documents

        class _Config:
            class _LLM:
                def __init__(self):
                    self.api_key = "test-key"

            def __init__(self):
                self.llm = self._LLM()
                self.system_prompt = None

        class _Retrieval:
            top_k = 20
            rerank_top_k = 8
            final_context_k = 5
            dense_weight = 0.55
            sparse_weight = 0.45
            reranker = "local"

        class _Embeddings:
            provider = "hash"
            model = "hash-384"

        class _Chunking:
            max_tokens = 320

        class _ConfigFull:
            def __init__(self):
                self.llm = _Config().llm
                self.system_prompt = None
                self.retrieval = _Retrieval()
                self.embeddings = _Embeddings()
                self.chunking = _Chunking()

        self.store = _Store(Path(":memory:"), chunks, documents)
        self.config = _ConfigFull()
        self._llm_client = llm_client or FakeLLMClient([])
        self.search_results: list = []
        self.answers: dict[str, str] = {}

    def search_with_profile(self, query, kb=None, filters=None):
        return self.search_results, {}

    def ask(self, query, kb=None, session_id=None, user_id=None, system_prompt=None):
        class _Answer:
            def __init__(self, text):
                self.text = text

        return _Answer(self.answers.get(query, f"Answer about {query}"))


def _make_chunk(chunk_id, document_id, doc_name, text):
    from rbs_rag.models import Chunk

    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        metadata={"document_name": doc_name, "tenant_id": "t1", "knowledge_base_id": "default"},
        embedding=[0.0] * 4,
    )


class EvaluationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "rag.db"
        self.store = EvaluationStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_case_crud(self):
        case = self.store.add_case("t1", "Where can I work from the hotel?", expected_document="coworking.html")
        self.assertTrue(case["case_id"])
        cases = self.store.list_cases("t1")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["expected_document"], "coworking.html")
        self.assertEqual(cases[0]["source"], "manual")

        updated = self.store.update_case(case["case_id"], {"expected_answer": "A coworking room"})
        self.assertEqual(updated["expected_answer"], "A coworking room")

        self.store.delete_case(case["case_id"])
        self.assertEqual(len(self.store.list_cases("t1")), 0)

    def test_run_lifecycle(self):
        run_id = self.store.create_run("t1", {"top_k": 20})
        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], "running")
        self.store.update_run(run_id, {"status": "completed", "overall_score": 0.8})
        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["overall_score"], 0.8)
        self.assertEqual(len(self.store.list_runs("t1")), 1)

    def test_document_hit(self):
        self.assertTrue(_document_hit({"document_name": "coworking.html"}, "coworking.html", None))
        self.assertTrue(_document_hit({"document_name": "coworking - Hotel X"}, "coworking", None))
        self.assertFalse(_document_hit({"document_name": "staff.html"}, "coworking", None))
        self.assertTrue(_document_hit({"chunk_id": "abc"}, None, "abc"))


class RunEvaluationTests(unittest.TestCase):
    def test_retrieval_miss_is_flagged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            case = store.add_case("t1", "Does the hotel have coworking?", expected_document="coworking.html")
            run_id = store.create_run("t1", {})

            engine = FakeEngine(chunks=[], documents=[])
            # Retrieval misses: returns a staff page instead
            engine.search_results = [
                type("R", (), {"chunk": _make_chunk("c1", "d1", "staff.html", "staff info"), "score": 0.9, "dense_score": 0.5, "sparse_score": 0.4})()
            ]
            engine.answers[case["question"]] = "Yes, coworking is available."

            with patch("rbs_rag.evaluation.create_llm_client", return_value=FakeLLMClient([])):
                summary = run_evaluation(engine, "t1", store, run_id)

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["total_cases"], 1)
            self.assertEqual(summary["passed_cases"], 0)
            self.assertEqual(summary["retrieval_hit_rate"], 0.0)

            results = store.get_run_results(run_id)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["failure_type"], "retrieval")
            self.assertFalse(results[0]["retrieval_hit"])
            self.assertEqual(results[0]["retrieved_chunks"][0]["document_name"], "staff.html")

    def test_ungraded_retrieval_passes_when_context_retrieved(self):
        """Cases without an expected source pass retrieval if any context is retrieved."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            case = store.add_case("t1", "What are the check-in times?")
            run_id = store.create_run("t1", {})

            engine = FakeEngine(chunks=[], documents=[])
            engine.search_results = [
                type("R", (), {"chunk": _make_chunk("c1", "d1", "checkin.html", "Check-in is from 2 PM."), "score": 0.9, "dense_score": 0.5, "sparse_score": 0.4})()
            ]
            engine.answers[case["question"]] = "Check-in is from 2 PM."

            with patch("rbs_rag.evaluation.create_llm_client", return_value=FakeLLMClient([])):
                summary = run_evaluation(engine, "t1", store, run_id)

            self.assertEqual(summary["retrieval_hit_rate"], 1.0)
            results = store.get_run_results(run_id)
            self.assertTrue(results[0]["retrieval_hit"])

    def test_retrieval_hit_with_lexical_judge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            case = store.add_case("t1", "Does the hotel have coworking?", expected_document="coworking.html")
            run_id = store.create_run("t1", {})

            engine = FakeEngine(chunks=[], documents=[])
            engine.search_results = [
                type("R", (), {"chunk": _make_chunk("c1", "d1", "coworking.html", "The hotel offers a coworking room with desks and fiber wifi."), "score": 0.95, "dense_score": 0.6, "sparse_score": 0.5})()
            ]
            engine.answers[case["question"]] = "Yes, the hotel offers a coworking room."

            # LLM judge raises -> lexical fallback (answer overlaps context heavily)
            class _Broken:
                def generate(self, messages):
                    raise RuntimeError("no llm")

            with patch("rbs_rag.evaluation.create_llm_client", return_value=_Broken()):
                summary = run_evaluation(engine, "t1", store, run_id)

            self.assertEqual(summary["retrieval_hit_rate"], 1.0)
            self.assertEqual(summary["passed_cases"], 1)
            self.assertGreaterEqual(summary["overall_score"], 0.5)

            results = store.get_run_results(run_id)
            self.assertEqual(results[0]["failure_type"], "none")
            self.assertTrue(results[0]["retrieval_hit"])


class GenerateAndQualityTests(unittest.TestCase):
    def test_generate_cases_parses_llm_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            chunk = _make_chunk("c1", "d1", "coworking.html", "The hotel provides a coworking room with two desks, printer, scanner and fiber Wi-Fi.")
            engine = FakeEngine(chunks=[chunk], documents=[], llm_client=FakeLLMClient([]))

            canned = json.dumps(
                [
                    {"question": "Does the hotel offer a place to work?", "expected_answer": "Yes", "expected_document": "coworking.html"},
                    {"question": "Can I work remotely from the hotel?", "expected_answer": "Yes", "expected_document": "coworking.html"},
                ]
            )

            with patch("rbs_rag.evaluation.create_llm_client", return_value=FakeLLMClient([canned])):
                created = generate_cases(engine, "t1", store, count=5)

            self.assertGreaterEqual(len(created), 2)
            cases = store.list_cases("t1")
            questions = {c["question"] for c in cases}
            self.assertIn("Does the hotel offer a place to work?", questions)
            self.assertTrue(all(c["source"] == "auto" for c in cases))

    def test_generate_fallback_terminates_with_short_chunks(self):
        """Deterministic fallback must not loop forever when chunks have no long lines."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            chunk = _make_chunk("c1", "d1", "short.html", "tiny")
            engine = FakeEngine(chunks=[chunk], documents=[], llm_client=FakeLLMClient([]))

            with patch("rbs_rag.evaluation.create_llm_client", return_value=FakeLLMClient([])):
                created = generate_cases(engine, "t1", store, count=10)

            self.assertLessEqual(len(created), 4)  # no infinite loop; bounded by cursor

    def test_kb_quality_reports_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            store = EvaluationStore(db)
            duplicate = _make_chunk("c1", "d1", "doc.md", "The quick brown fox jumps over the lazy dog.")
            duplicate2 = _make_chunk("c2", "d1", "doc.md", "The quick brown fox jumps over the lazy dog.")
            tiny = _make_chunk("c3", "d2", "other.md", "ok")
            engine = FakeEngine(chunks=[duplicate, duplicate2, tiny], documents=[])

            quality = kb_quality(engine, "t1")
            self.assertEqual(quality["chunks"], 3)
            self.assertEqual(quality["documents"], 0)
            self.assertGreaterEqual(quality["duplicate_pct"], 33.0)
            self.assertGreaterEqual(quality["tiny_pct"], 33.0)
            self.assertGreaterEqual(quality["quality_score"], 0)
            self.assertLessEqual(quality["quality_score"], 100)


if __name__ == "__main__":
    unittest.main()
