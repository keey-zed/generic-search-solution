from __future__ import annotations

from pathlib import Path

import pytest

from app.api import SearchEngine, SearchRequest
from app.core.config.models import BrandingConfig, FrontendConfig, SearchConfig, UseCaseConfig
from app.core.embeddings import InlineEmbeddingProvider
from app.core.schema.embedding import EmbeddedDocumentRecord, Embedding
from app.core.schema.metadata_types import NormalizedDocument


class DeterministicTextEmbedder:
    """Small model substitute proving the generic contract, not ML quality."""

    model_id = "deterministic-test-model"

    def __init__(self):
        self.document_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [1.0, 0.0] if "tax" in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts):
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_queries(self, texts):
        return [self._vector(text) for text in texts]


def _documents() -> list[NormalizedDocument]:
    return [
        NormalizedDocument(id="tax", text="tax regulations and fiscal rules", metadata={}),
        NormalizedDocument(id="health", text="hospital administration", metadata={}),
    ]


def _config() -> UseCaseConfig:
    return UseCaseConfig(
        schema_version=1,
        filters={},
        search=SearchConfig(),
        frontend=FrontendConfig(branding=BrandingConfig(title="Semantic test")),
    )


def test_semantic_text_query_uses_the_generic_text_embedder(tmp_path: Path):
    from app.embeddings import load_or_create_document_embeddings

    embedder = DeterministicTextEmbedder()
    documents = _documents()
    embeddings = load_or_create_document_embeddings(documents, embedder, cache_path=tmp_path / "vectors.json")
    provider = InlineEmbeddingProvider(
        [
            EmbeddedDocumentRecord(id=document.id, text=document.text, metadata={}, embedding=embeddings[document.id])
            for document in documents
        ]
    )
    engine = SearchEngine(_config(), {}, documents, embedding_provider=provider, text_embedder=embedder)

    page = engine.search(SearchRequest(semantic_text=["tax obligations"]))

    assert page.total_hits == 2
    assert page.hits[0].id == "tax"


def test_embedding_cache_reuses_unchanged_document_vectors(tmp_path: Path):
    from app.embeddings import load_or_create_document_embeddings

    embedder = DeterministicTextEmbedder()
    cache_path = tmp_path / "vectors.json"

    first = load_or_create_document_embeddings(_documents(), embedder, cache_path=cache_path)
    second = load_or_create_document_embeddings(_documents(), embedder, cache_path=cache_path)

    assert embedder.document_calls == 1
    assert first == second


def test_engine_rejects_different_document_and_query_models():
    class OtherModel(DeterministicTextEmbedder):
        model_id = "other-model"

    documents = _documents()
    provider = InlineEmbeddingProvider(
        [
            EmbeddedDocumentRecord(
                id="tax",
                text="tax",
                metadata={},
                embedding=Embedding(vector=[1.0], model_id="model-a"),
            )
        ]
    )

    with pytest.raises(ValueError, match="different models"):
        SearchEngine(_config(), {}, documents, embedding_provider=provider, text_embedder=OtherModel())
