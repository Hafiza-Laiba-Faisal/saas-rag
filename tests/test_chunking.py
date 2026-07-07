import unittest

from rbs_rag.chunking import HierarchicalChunker
from rbs_rag.models import LoadedDocument


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


if __name__ == "__main__":
    unittest.main()

