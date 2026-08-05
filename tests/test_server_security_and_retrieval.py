import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rbs_rag.retrieval import HybridRetriever
import importlib.util

spec = importlib.util.spec_from_file_location("server_module", Path(__file__).resolve().parents[1] / "src/rbs_rag/web/server.py")
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class DummyEmbeddingProvider:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


class DummyStore:
    def list_chunks(self, tenant_id, knowledge_base_id, filters):
        return []


class DummyVectorStore:
    def __init__(self):
        self.filters = None

    def search(self, collection, query_embedding, top_k=20, filters=None):
        self.filters = filters
        return []


class StubReranker:
    def rerank(self, query, candidates, final_context_k):
        return candidates


class ServerSecurityAndRetrievalTests(unittest.TestCase):
    def test_search_passes_tenant_filter_to_vector_store(self):
        vector_store = DummyVectorStore()
        retriever = HybridRetriever(
            store=DummyStore(),
            embedding_provider=DummyEmbeddingProvider(),
            tenant_id="tenant-a",
            vector_store=vector_store,
        )

        with patch("rbs_rag.retrieval.create_reranker", return_value=StubReranker()):
            retriever.search_with_profile("hello", "kb-1", filters={"department": "support"})

        self.assertEqual(vector_store.filters["tenant_id"], "tenant-a")
        self.assertEqual(vector_store.filters["knowledge_base_id"], "kb-1")
        self.assertEqual(vector_store.filters["department"], "support")

    def test_resolve_document_path_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir) / "documents"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "safe.txt").write_text("hello", encoding="utf-8")

            with self.assertRaises(ValueError):
                server_module._resolve_tenant_document_path("tenant-a", "../secret.txt", docs_dir)

    def test_list_documents_classifies_content_header_scraped_files_as_scrape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            docs_dir = root_dir / "tenant-a" / "documents"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "page.md").write_text("# Page\n\nSource: https://example.com\n\nBody", encoding="utf-8")

            original_tenants_dir = server_module.TENANTS_DIR
            try:
                server_module.TENANTS_DIR = root_dir
                with patch.object(server_module, "_sync_crawl_outputs_to_tenant", return_value=[]):
                    items = server_module._list_documents_from_db(root_dir / "tenant.db", "tenant-a")
            finally:
                server_module.TENANTS_DIR = original_tenants_dir

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["source"], "scrape")
            self.assertEqual(items[0]["source_url"], "https://example.com")


if __name__ == "__main__":
    unittest.main()
