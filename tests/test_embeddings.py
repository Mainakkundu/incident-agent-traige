from __future__ import annotations

import unittest

from src.embeddings import HuggingFaceEmbeddingProvider


class EmbeddingTests(unittest.TestCase):
    def test_huggingface_embedding_provider_calls_configured_model(self) -> None:
        model = FakeSentenceTransformer()
        provider = HuggingFaceEmbeddingProvider(
            model_name="sentence-transformers/all-mpnet-base-v2",
            model=model,
        )

        vector = provider.embed_query("postgres max connections")

        self.assertEqual(vector, [0.1, 0.2, 0.3])
        self.assertEqual(provider.model_name, "sentence-transformers/all-mpnet-base-v2")
        self.assertEqual(model.sentences, "postgres max connections")
        self.assertTrue(model.normalize_embeddings)

    def test_huggingface_embedding_provider_requires_model_name(self) -> None:
        with self.assertRaises(ValueError):
            HuggingFaceEmbeddingProvider(model_name="")


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.sentences = ""
        self.normalize_embeddings = False

    def encode(
        self,
        sentences: str,
        normalize_embeddings: bool = True,
    ) -> list[float]:
        self.sentences = sentences
        self.normalize_embeddings = normalize_embeddings
        return [0.1, 0.2, 0.3]


if __name__ == "__main__":
    unittest.main()
