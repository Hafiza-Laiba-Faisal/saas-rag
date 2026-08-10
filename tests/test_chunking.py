import tempfile
import unittest
from pathlib import Path

from rbs_rag.chunking import HierarchicalChunker, _boilerplate_reason
from rbs_rag.evaluation import EvaluationStore
from rbs_rag.models import Chunk, LoadedDocument
from rbs_rag.store import SQLiteRagStore


class ChunkingTests(unittest.TestCase):
    def test_chunker_respects_token_limit_and_keeps_section_metadata(self):
        text = "# Refunds\n" + "refund policy applies to orders " * 40 + "\n# Shipping\n" + "shipping policy applies " * 35
        document = LoadedDocument(
            document_id="doc-1",
            path="policy.md",
            name="policy.md",
            document_type="md",
            text=text,
            metadata={"department": "support"},
        )
        chunker = HierarchicalChunker(max_tokens=32, overlap_tokens=6)

        chunks = chunker.chunk(document, tenant_id="local", knowledge_base_id="kb")

        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk.text.split()) <= 32 for chunk in chunks))
        self.assertIn("section", chunks[0].metadata)
        self.assertEqual(chunks[0].metadata["department"], "support")


class BoilerplateFilterTests(unittest.TestCase):
    def _doc(self, text: str, name: str = "page.md") -> LoadedDocument:
        return LoadedDocument(
            document_id=f"doc-{name}",
            path=name,
            name=name,
            document_type="md",
            text=text,
            metadata={},
        )

    def test_boilerplate_reason_detects_junk(self):
        self.assertEqual(_boilerplate_reason("Source: https://example.com/"), "source_header")
        self.assertEqual(
            _boilerplate_reason("We use cookies to enhance your experience. By continuing you accept our Privacy Policy."),
            "cookie_banner",
        )
        self.assertEqual(_boilerplate_reason("© 2024 Hotel X. All rights reserved. Terms of use apply."), "legal_boilerplate")
        self.assertIsNone(_boilerplate_reason("The hotel offers a coworking room with two desks, printer and fiber Wi-Fi."))

    def test_faq_explainer_content_is_not_filtered(self):
        # Real informational content mentioning cookies must NOT be dropped.
        self.assertIsNone(
            _boilerplate_reason("What are cookies? Cookies are small text files a site stores on your device to remember your preferences and improve your experience.")
        )
        self.assertIsNone(
            _boilerplate_reason("How do we use your data? We collect usage statistics to improve our services and never sell personal information to third parties.")
        )

    def test_language_codes_match_only_as_whole_words(self):
        # "it" inside "site", "en" inside "when", "de" inside "desk" must NOT
        # count as language names — substring matching would false-positive.
        self.assertIsNone(
            _boilerplate_reason("The front desk is open all day. Site visitors can request a map at any time.")
        )
        # A real language switcher with an explicit marker and two languages.
        self.assertEqual(
            _boilerplate_reason("Select your language: English Deutsch Français"),
            "language_switcher",
        )
        self.assertEqual(
            _boilerplate_reason("Switch language — IT EN FR DE ES"),
            "language_switcher",
        )

    def test_chunker_filters_cookie_banner_and_source_lines(self):
        text = (
            "# Hotel\n"
            "The hotel offers coworking rooms with desks and fiber Wi-Fi.\n\n"
            "Source: https://example.com/coworking\n\n"
            "We use cookies to enhance your experience. By continuing you accept our Privacy Policy and Terms of Use. "
            "Manage consent at any time. Cookies help us improve our site and analyze traffic.\n"
        )
        chunker = HierarchicalChunker(max_tokens=64, overlap_tokens=0)
        chunks = chunker.chunk(self._doc(text), tenant_id="t", knowledge_base_id="kb")

        self.assertGreater(chunker.stats["filtered"], 0)
        joined = " ".join(c.text for c in chunks).lower()
        self.assertIn("coworking", joined)
        self.assertNotIn("cookie", joined)
        self.assertNotIn("source: https", joined)

    def test_chunker_dedupes_repeated_sentences(self):
        repeated = "The hotel has free Wi-Fi in all rooms. " * 5
        text = f"# Hotel\n{repeated}\n\n{repeated}"
        chunker = HierarchicalChunker(max_tokens=32, overlap_tokens=0)
        chunks = chunker.chunk(self._doc(text), tenant_id="t", knowledge_base_id="kb")

        self.assertGreater(chunker.stats["deduped"], 0)
        sigs = [c.text.lower() for c in chunks]
        self.assertEqual(len(sigs), len(set(sigs)))

    def test_chunker_can_be_disabled(self):
        text = "Source: https://example.com/\n\nWe use cookies. Accept all cookies. Cookie preferences."
        chunker = HierarchicalChunker(max_tokens=64, overlap_tokens=0, filter_boilerplate=False, dedupe_within_document=False)
        chunks = chunker.chunk(self._doc(text), tenant_id="t", knowledge_base_id="kb")
        self.assertGreaterEqual(len(chunks), 1)


class StoreDedupTests(unittest.TestCase):
    def _doc(self, doc_id: str, name: str = "") -> LoadedDocument:
        return LoadedDocument(
            document_id=doc_id,
            path=f"{name or doc_id}.md",
            name=name or f"{doc_id}.md",
            document_type="md",
            text=f"content of {doc_id}",
            metadata={},
        )

    def _chunk(self, chunk_id: str, doc_id: str, text: str) -> Chunk:
        return Chunk(
            chunk_id=chunk_id,
            document_id=doc_id,
            text=text,
            metadata={"tenant_id": "t1", "knowledge_base_id": "default", "document_name": f"{doc_id}.md"},
            embedding=[0.0, 0.0, 0.0, 0.0],
            ordinal=0,
        )

    def _upsert_doc(self, store: SQLiteRagStore, doc_id: str):
        store.upsert_document(self._doc(doc_id), "t1", "default")

    def test_upsert_skips_cross_document_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRagStore(Path(temp_dir) / "rag.db")
            text = "The hotel offers coworking rooms with desks and fiber Wi-Fi."

            self._upsert_doc(store, "d1")
            kept1 = store.upsert_chunks([self._chunk("c1", "d1", text)])
            self.assertEqual(len(kept1), 1)

            # Same normalized text from a second page -> deduped
            self._upsert_doc(store, "d2")
            kept2 = store.upsert_chunks([self._chunk("c2", "d2", f"  {text}  ")])
            self.assertEqual(len(kept2), 0)

            self.assertEqual(store.count_chunks("t1", "default"), 1)

    def test_upsert_keeps_unique_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRagStore(Path(temp_dir) / "rag.db")
            self._upsert_doc(store, "d1")
            kept = store.upsert_chunks(
                [self._chunk("c1", "d1", "Coworking area with two desks."), self._chunk("c2", "d1", "Breakfast served from 7 AM.")]
            )
            self.assertEqual(len(kept), 2)
            self.assertEqual(store.count_chunks("t1", "default"), 2)

    def test_dedup_survives_eval_store_tables(self):
        # Ensure the dedup scan works alongside evaluation tables in the same DB.
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "rag.db"
            EvaluationStore(db)  # creates eval tables in the same file
            store = SQLiteRagStore(db)
            text = "Free cancellation up to 48 hours before arrival."
            self._upsert_doc(store, "d1")
            kept1 = store.upsert_chunks([self._chunk("c1", "d1", text)])
            self._upsert_doc(store, "d2")
            kept2 = store.upsert_chunks([self._chunk("c2", "d2", text)])
            self.assertEqual(len(kept1), 1)
            self.assertEqual(len(kept2), 0)

    def test_fully_deduped_document_does_not_count_as_new(self):
        # When every chunk of a doc is a duplicate, the doc row is kept (so
        # re-ingestion skips it) but upsert_chunks must report zero kept.
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRagStore(Path(temp_dir) / "rag.db")
            text = "The rooftop bar serves cocktails until midnight with a sea view."
            self._upsert_doc(store, "d1")
            kept1 = store.upsert_chunks([self._chunk("c1", "d1", text)])
            self.assertEqual(len(kept1), 1)

            self._upsert_doc(store, "d2")
            kept2 = store.upsert_chunks([self._chunk("c2", "d2", text)])
            self.assertEqual(len(kept2), 0)
            self.assertEqual(store.count_chunks("t1", "default"), 1)
            # The document row itself remains (marks it as ingested).
            self.assertIsNotNone(store.get_document("d2"))


if __name__ == "__main__":
    unittest.main()

