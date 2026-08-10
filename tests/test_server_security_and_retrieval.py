import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rbs_rag.retrieval import HybridRetriever
from rbs_rag.store import SQLiteRagStore
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

    def test_crawl_output_sync_stays_scoped_to_the_current_tenant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            tenants_dir = root_dir / "tenants"
            docs_dir_a = tenants_dir / "tenant-a" / "documents"
            docs_dir_b = tenants_dir / "tenant-b" / "documents"
            docs_dir_a.mkdir(parents=True, exist_ok=True)
            docs_dir_b.mkdir(parents=True, exist_ok=True)

            original_root_dir = server_module.ROOT_DIR
            original_tenants_dir = server_module.TENANTS_DIR
            original_crawl_output_dir = server_module.CRAWL_OUTPUT_DIR
            try:
                server_module.ROOT_DIR = root_dir
                server_module.TENANTS_DIR = tenants_dir
                server_module.CRAWL_OUTPUT_DIR = root_dir / "crawl-output"

                server_module._save_crawl_output(
                    site="tenant-a.example",
                    metadata={"source_url": "https://tenant-a.example"},
                    pages=["# Tenant A\n\nSource: https://tenant-a.example\n\nBody A"],
                    tenant_id="tenant-a",
                )
                server_module._save_crawl_output(
                    site="tenant-b.example",
                    metadata={"source_url": "https://tenant-b.example"},
                    pages=["# Tenant B\n\nSource: https://tenant-b.example\n\nBody B"],
                    tenant_id="tenant-b",
                )

                with patch.object(server_module.admin_store, "get_tenant", side_effect=lambda tenant_id: {"tenant_id": tenant_id, "crawl_output_dir": str(server_module._tenant_crawl_output_root(tenant_id))}):
                    saved = server_module._sync_crawl_outputs_to_tenant("tenant-a")
            finally:
                server_module.ROOT_DIR = original_root_dir
                server_module.TENANTS_DIR = original_tenants_dir
                server_module.CRAWL_OUTPUT_DIR = original_crawl_output_dir

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["url"], "https://tenant-a.example")
            self.assertTrue((docs_dir_a / saved[0]["file"]).exists())
            self.assertFalse((docs_dir_b / saved[0]["file"]).exists())

    def test_store_migrates_session_turns_table_for_existing_databases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "rag.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE session_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO session_turns (tenant_id, session_id, user_id, role, content) VALUES (?, ?, ?, ?, ?)",
                    ("tenant-a", "session-1", "user-1", "user", "hello"),
                )
                conn.commit()
            finally:
                conn.close()

            store = SQLiteRagStore(db_path)
            sessions = store.list_sessions("tenant-a")

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], "session-1")
            self.assertEqual(store.get_session_turns("tenant-a", "session-1")[0]["content"], "hello")

    def test_tenant_connection_context_manager_closes_connection(self):
        # Regression: `with sqlite3.connect(...) as conn:` commits but NEVER
        # closes the connection — under load the process exhausts file
        # descriptors and every DB call fails with "unable to open database".
        # The context manager must close the connection on exit.
        from unittest.mock import MagicMock, patch

        conn = MagicMock()
        with patch.object(server_module.sqlite3, "connect", return_value=conn) as mock_connect:
            with server_module._tenant_connection(Path("/tmp/fake-tenant/rag.db")) as cm_conn:
                self.assertIs(cm_conn, conn)
            mock_connect.assert_called_once()
            conn.close.assert_called_once()

        # Same guarantee for the admin DB connection.
        from rbs_rag.web import admin_db
        from rbs_rag.web.admin_db import AdminStore

        admin = AdminStore(Path(tempfile.mkdtemp()) / "admin.db")
        conn2 = MagicMock()
        with patch.object(admin_db.sqlite3, "connect", return_value=conn2) as mock_connect2:
            with admin._connect() as cm_conn2:
                self.assertIs(cm_conn2, conn2)
            mock_connect2.assert_called_once()
            conn2.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
