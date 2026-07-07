import json
import os
import tempfile
import unittest
from pathlib import Path

from rbs_rag.config import AppConfig, create_default_config, load_config


class ConfigTests(unittest.TestCase):
    def test_create_default_config_writes_local_storage_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            path = create_default_config(root)

            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["tenant_id"], "local")
            self.assertEqual(data["default_kb"], "default")
            self.assertEqual(data["storage"]["provider"], "sqlite")

    def test_load_config_expands_environment_variables_without_printing_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / ".rbs_rag"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "tenant_id": "local",
                        "default_kb": "kb1",
                        "storage": {"provider": "sqlite", "path": ".rbs_rag/rag.db"},
                        "embeddings": {"provider": "hash", "dimensions": 64},
                        "retrieval": {"top_k": 10, "rerank_top_k": 4, "final_context_k": 3},
                        "llm": {
                            "provider": "openai_compatible",
                            "api_key": "${RAG_TEST_KEY}",
                            "model": "test-model",
                            "base_url": "https://example.test/v1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            os.environ["RAG_TEST_KEY"] = "secret-value"

            config = load_config(root)

            self.assertIsInstance(config, AppConfig)
            self.assertEqual(config.llm.api_key, "secret-value")
            self.assertEqual(config.default_kb, "kb1")

    def test_load_config_reads_env_local_when_process_env_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_default_config(root)
            (root / ".env.local").write_text("RAG_LLM_API_KEY=local-secret\n", encoding="utf-8")
            os.environ.pop("RAG_LLM_API_KEY", None)

            config = load_config(root)

            self.assertEqual(config.llm.api_key, "local-secret")


if __name__ == "__main__":
    unittest.main()
