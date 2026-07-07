import tempfile
import unittest
from pathlib import Path

from rbs_rag.config import create_default_config, load_config
from rbs_rag.engine import RagEngine


class EngineRetrievalTests(unittest.TestCase):
    def test_ingest_and_search_returns_relevant_cited_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_default_config(root)
            docs = root / "docs"
            docs.mkdir()
            (docs / "policy.md").write_text(
                "# Refund Policy\nCustomers can request a refund within 30 days when they provide an order receipt.\n"
                "# Shipping Policy\nStandard shipping takes five business days.\n",
                encoding="utf-8",
            )
            engine = RagEngine(load_config(root), root)

            summary = engine.ingest_path(docs, kb="default", metadata={"department": "support"})
            results = engine.search("How long do customers have to request a refund?", kb="default")

            self.assertEqual(summary.documents, 1)
            self.assertGreaterEqual(summary.chunks, 1)
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("refund", results[0].chunk.text.lower())
            self.assertEqual(results[0].chunk.metadata["document_name"], "policy.md")

    def test_metadata_filter_isolates_knowledge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_default_config(root)
            docs = root / "docs"
            docs.mkdir()
            (docs / "hr.md").write_text("Refunds for HR training fees require manager approval.", encoding="utf-8")
            (docs / "support.md").write_text("Customer refunds are available for eligible support tickets.", encoding="utf-8")
            engine = RagEngine(load_config(root), root)

            engine.ingest_file(docs / "hr.md", kb="default", metadata={"department": "hr"})
            engine.ingest_file(docs / "support.md", kb="default", metadata={"department": "support"})
            results = engine.search("refunds", kb="default", filters={"department": "support"})

            self.assertGreaterEqual(len(results), 1)
            self.assertTrue(all(result.chunk.metadata["department"] == "support" for result in results))

    def test_user_memory_is_saved_and_rendered_for_answers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_default_config(root)
            engine = RagEngine(load_config(root), root)

            engine.set_user_memory("alice", "role", "support manager")
            memory = engine.get_user_memory_text("alice")

            self.assertIn("role: support manager", memory)


if __name__ == "__main__":
    unittest.main()
