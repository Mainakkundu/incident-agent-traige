"""Hugging Face embedding provider."""

from __future__ import annotations

from typing import Any, Protocol, Sequence


class SentenceTransformerLike(Protocol):
    """Minimal sentence-transformer interface."""

    def encode(
        self,
        sentences: str,
        normalize_embeddings: bool = True,
    ) -> Any:
        """Return one embedding."""
        ...


class HuggingFaceEmbeddingProvider:
    """Embedding provider backed by a local Hugging Face sentence-transformer."""

    def __init__(
        self,
        model_name: str,
        model: SentenceTransformerLike | None = None,
    ) -> None:
        if not model_name:
            msg = "embedding model is required"
            raise ValueError(msg)

        self.model_name = model_name
        self.model = model or create_sentence_transformer(model_name)

    def embed_query(self, text: str) -> Sequence[float]:
        """Return one embedding vector for query text."""
        embedding = self.model.encode(text, normalize_embeddings=True)
        if hasattr(embedding, "tolist"):
            values = embedding.tolist()
        else:
            values = list(embedding)
        return [float(value) for value in values]


def create_sentence_transformer(model_name: str) -> SentenceTransformerLike:
    """Return a sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        msg = "Install sentence-transformers with: pip install sentence-transformers"
        raise RuntimeError(msg) from exc
    return SentenceTransformer(model_name)
