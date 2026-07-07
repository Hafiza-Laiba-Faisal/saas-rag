import unittest
from unittest.mock import patch

from rbs_rag.llm import GeminiClient, LLMSettings, build_rag_messages, detect_llm_provider
from rbs_rag.models import Chunk, SearchResult


class LLMTests(unittest.TestCase):
    def test_detects_gemini_from_api_key_or_base_url(self):
        self.assertEqual(
            detect_llm_provider(LLMSettings(api_key="AIza-test", model="gemini-2.5-flash")),
            "gemini",
        )
        self.assertEqual(
            detect_llm_provider(
                LLMSettings(api_key="key", model="gemini-2.5-flash", base_url="https://generativelanguage.googleapis.com/v1beta")
            ),
            "gemini",
        )

    def test_explicit_provider_wins_over_detection(self):
        settings = LLMSettings(provider="openai_compatible", api_key="AIza-test", model="custom")

        self.assertEqual(detect_llm_provider(settings), "openai_compatible")

    def test_build_rag_messages_include_citations_and_memory(self):
        chunk = Chunk(
            chunk_id="c1",
            document_id="d1",
            text="Refund requests are accepted within 30 days.",
            metadata={"document_name": "policy.md", "section": "Refunds"},
            embedding=[],
        )
        result = SearchResult(chunk=chunk, score=0.9, dense_score=0.8, sparse_score=0.7, rerank_score=0.6)

        messages = build_rag_messages("When can I get a refund?", [result], session_memory="User asked about orders.")

        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("[1]", joined)
        self.assertIn("policy.md", joined)
        self.assertIn("User asked about orders.", joined)

    def test_gemini_client_retries_fallback_model_on_overload(self):
        settings = LLMSettings(
            provider="gemini",
            api_key="secret",
            model="busy-model",
            fallback_models=["gemini-2.5-flash-lite"],
        )
        messages = [{"role": "user", "content": "hello"}]

        with patch(
            "rbs_rag.llm._post_json",
            side_effect=[
                RuntimeError('LLM API request failed with HTTP 503: {"error": {"status": "UNAVAILABLE"}}'),
                {"candidates": [{"content": {"parts": [{"text": "fallback answer"}]}}]},
            ],
        ) as post_json:
            answer = GeminiClient(settings).generate(messages)

        self.assertEqual(answer, "fallback answer")
        self.assertIn("busy-model", post_json.call_args_list[0].args[0])
        self.assertIn("gemini-2.5-flash-lite", post_json.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
