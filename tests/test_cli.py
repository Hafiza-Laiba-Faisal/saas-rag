import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from rbs_rag.cli import _clean_text_for_encoding, main


class CLITests(unittest.TestCase):
    def test_clean_text_for_encoding_replaces_unprintable_characters(self):
        self.assertEqual(_clean_text_for_encoding("Document ↓ flow", "cp1252"), "Document ? flow")

    def test_init_ingest_and_search_cli_flow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "handbook.txt").write_text("The handbook says refunds are available for 30 days.", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()) as init_output:
                self.assertEqual(main(["--root", str(root), "init"]), 0)
            self.assertIn("Created config", init_output.getvalue())

            with contextlib.redirect_stdout(io.StringIO()) as ingest_output:
                self.assertEqual(main(["--root", str(root), "ingest", str(docs), "--kb", "default"]), 0)
            self.assertIn("Indexed", ingest_output.getvalue())

            with contextlib.redirect_stdout(io.StringIO()) as search_output:
                self.assertEqual(main(["--root", str(root), "search", "refunds", "--kb", "default"]), 0)
            self.assertIn("handbook.txt", search_output.getvalue())
            self.assertIn("refunds", search_output.getvalue().lower())

            with contextlib.redirect_stdout(io.StringIO()) as documents_output:
                self.assertEqual(main(["--root", str(root), "documents", "list", "--kb", "default"]), 0)
            self.assertIn("handbook.txt", documents_output.getvalue())


if __name__ == "__main__":
    unittest.main()
