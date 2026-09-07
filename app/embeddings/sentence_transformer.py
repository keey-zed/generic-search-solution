"""SentenceTransformer implementation of the generic text embedder."""
from __future__ import annotations

from typing import Sequence


class SentenceTransformerTextEmbedder:
    """Embed text locally with a SentenceTransformer model.

    E5-family models require distinct ``passage:`` and ``query:`` prefixes.
    They are enabled by default because the legacy semantic engine uses
    multilingual E5.  For a model that does not use prefixes, pass empty
    strings for ``document_prefix`` and ``query_prefix``.
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
        *,
        device: str | None = None,
        batch_size: int = 32,
        document_prefix: str = "passage: ",
        query_prefix: str = "query: ",
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix
        self._model = None

    @property
    def model_id(self) -> str:
        return f"sentence-transformers:{self._model_name}"

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - installation dependent
                raise RuntimeError(
                    "semantic text embedding requires sentence-transformers. "
                    "Install this project's `legacy-app` extra."
                ) from exc
            self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model

    def _embed(self, texts: Sequence[str], *, prefix: str) -> list[list[float]]:
        if not texts:
            return []
        encoded = self._get_model().encode(
            [f"{prefix}{text}" for text in texts],
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in encoded]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, prefix=self._document_prefix)

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, prefix=self._query_prefix)
