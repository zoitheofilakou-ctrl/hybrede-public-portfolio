import unittest
from unittest.mock import Mock, patch

from llm import rag_generator as rg
from Retrieval import retrieval


class OfflineModelLoadingTests(unittest.TestCase):
    def tearDown(self):
        retrieval.get_embedding_model.cache_clear()
        retrieval.get_cross_encoder_model.cache_clear()

    def test_embedding_and_cross_encoder_are_local_only_and_identical(self):
        embedding = Mock()
        cross = Mock()
        with patch.object(retrieval, "SentenceTransformer", return_value=embedding) as st, \
             patch.object(retrieval, "CrossEncoder", return_value=cross) as ce:
            self.assertIs(embedding, retrieval.get_embedding_model())
            self.assertIs(cross, retrieval.get_cross_encoder_model())
        st.assert_called_once_with(retrieval.EMBED_MODEL_NAME, local_files_only=True)
        ce.assert_called_once_with(retrieval.CROSS_ENCODER_MODEL_NAME, local_files_only=True)

    def test_missing_local_models_fail_closed_without_substitution(self):
        with patch.object(retrieval, "SentenceTransformer", side_effect=OSError("cache miss")):
            with self.assertRaisesRegex(RuntimeError, retrieval.EMBED_MODEL_NAME):
                retrieval.get_embedding_model()
        retrieval.get_embedding_model.cache_clear()
        with patch.object(retrieval, "CrossEncoder", side_effect=OSError("cache miss")):
            with self.assertRaisesRegex(RuntimeError, retrieval.CROSS_ENCODER_MODEL_NAME):
                retrieval.get_cross_encoder_model()

    def test_multiple_calls_reuse_verified_local_instances(self):
        with patch.object(retrieval, "SentenceTransformer", return_value=object()) as loader:
            first = retrieval.get_embedding_model()
            second = retrieval.get_embedding_model()
        self.assertIs(first, second)
        loader.assert_called_once()


class BatchLifecycleTests(unittest.TestCase):
    def resources(self):
        llm = Mock()
        llm.client = Mock()
        collection = Mock()
        embedding = Mock()
        return llm, collection, embedding

    def test_borrowed_resources_survive_two_sequential_cases(self):
        llm, collection, embedding = self.resources()
        with patch.object(rg, "generate_rag_answer", side_effect=[
            {"query": "diagnostic one"}, {"query": "diagnostic two"}
        ]) as generate:
            rows = rg.evaluate_query_batch(
                ["diagnostic one", "diagnostic two"], llm=llm,
                collection=collection, embedding_model=embedding,
            )
        self.assertEqual(2, len(rows))
        self.assertEqual(2, generate.call_count)
        llm.client.close.assert_not_called()

    def test_owner_closes_exactly_once_after_complete_batch(self):
        llm, collection, embedding = self.resources()
        order = []
        llm.client.close.side_effect = lambda: order.append("close")
        with patch.object(rg, "get_llm_provider", return_value=llm), \
             patch.object(rg, "generate_rag_answer",
                          side_effect=lambda query, **_: order.append(query) or {"query": query}):
            rows = rg.evaluate_query_batch(
                ["one", "two", "three"], collection=collection,
                embedding_model=embedding,
            )
        self.assertEqual(3, len(rows))
        self.assertEqual(["one", "two", "three", "close"], order)
        llm.client.close.assert_called_once_with()

    def test_exception_does_not_reuse_a_closed_client(self):
        llm, collection, embedding = self.resources()
        def execute(query, **_):
            if query == "bad":
                raise ValueError("diagnostic failure")
            if llm.client.close.called:
                raise RuntimeError("closed resource reused")
            return {"query": query}
        with patch.object(rg, "generate_rag_answer", side_effect=execute):
            rows = rg.evaluate_query_batch(
                ["first", "bad", "third"], llm=llm,
                collection=collection, embedding_model=embedding,
            )
        self.assertFalse(rows[0].get("technical_failure", False))
        self.assertTrue(rows[1]["technical_failure"])
        self.assertFalse(rows[2].get("technical_failure", False))
        llm.client.close.assert_not_called()

    def test_independent_owned_batches_get_independent_clients(self):
        clients = []
        def factory(*_, **__):
            provider = Mock()
            provider.client = Mock()
            clients.append(provider)
            return provider
        _, collection, embedding = self.resources()
        with patch.object(rg, "get_llm_provider", side_effect=factory), \
             patch.object(rg, "generate_rag_answer", return_value={"ok": True}):
            rg.evaluate_query_batch(["a"], collection=collection, embedding_model=embedding)
            rg.evaluate_query_batch(["b"], collection=collection, embedding_model=embedding)
        self.assertEqual(2, len(clients))
        self.assertIsNot(clients[0], clients[1])
        for provider in clients:
            provider.client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
