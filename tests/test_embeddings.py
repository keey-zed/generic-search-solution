import pytest
from pydantic import ValidationError

from app.core.schema.document import DocumentRecord
from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def test_embedding_dim_derived_from_vector():
    e = Embedding(vector=[0.1, 0.2, 0.3], model_id="bge-m3")
    assert e.dim == 3


def test_embedding_rejects_empty_vector():
    with pytest.raises(ValidationError):
        Embedding(vector=[], model_id="bge-m3")


def test_embedding_rejects_nan():
    with pytest.raises(ValidationError):
        Embedding(vector=[0.1, float("nan")], model_id="bge-m3")


def test_embedding_rejects_inf():
    with pytest.raises(ValidationError):
        Embedding(vector=[0.1, float("inf")], model_id="bge-m3")


def test_embedding_requires_model_id():
    with pytest.raises(ValidationError):
        Embedding(vector=[0.1, 0.2])


def test_embedding_rejects_blank_model_id():
    with pytest.raises(ValidationError):
        Embedding(vector=[0.1, 0.2], model_id="   ")


def test_embedding_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        Embedding(vector=[0.1, 0.2], model_id="bge-m3", dim=2)


# ---------------------------------------------------------------------------
# EmbeddedDocumentRecord
# ---------------------------------------------------------------------------


def test_embedded_document_record_embedding_optional_defaults_none():
    r = EmbeddedDocumentRecord(id="doc-1", text="hello", metadata={})
    assert r.embedding is None


def test_embedded_document_record_with_embedding():
    r = EmbeddedDocumentRecord(
        id="doc-1",
        text="hello",
        metadata={"doctype": "dahir"},
        embedding=Embedding(vector=[0.1, 0.2], model_id="bge-m3"),
    )
    assert r.embedding.dim == 2
    assert r.embedding.model_id == "bge-m3"


def test_embedded_document_record_is_a_document_record():
    r = EmbeddedDocumentRecord(id="doc-1", text="hello", metadata={})
    assert isinstance(r, DocumentRecord)


def test_embedded_document_record_backwards_compatible_with_plain_dict():
    """A dict shaped like an existing (pre-embedding) DocumentRecord must
    still validate as an EmbeddedDocumentRecord with no changes needed."""
    plain = {"id": "doc-1", "text": "hello", "metadata": {"a": "x"}}
    r = EmbeddedDocumentRecord(**plain)
    assert r.embedding is None
    assert r.metadata == {"a": "x"}


def test_document_record_itself_still_rejects_embedding_field():
    """DocumentRecord (Layer 0) must remain untouched: embeddings only
    exist on the separate EmbeddedDocumentRecord model."""
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={}, embedding=[0.1, 0.2])


# ---------------------------------------------------------------------------
# InlineEmbeddingProvider
# ---------------------------------------------------------------------------


def _rec(id_, vector=None, model_id="bge-m3"):
    embedding = Embedding(vector=vector, model_id=model_id) if vector is not None else None
    return EmbeddedDocumentRecord(id=id_, text="text", metadata={}, embedding=embedding)


def test_inline_provider_satisfies_embedding_provider_protocol():
    provider = InlineEmbeddingProvider([])
    assert isinstance(provider, EmbeddingProvider)


def test_inline_provider_returns_embedding_for_known_id():
    records = [_rec("doc-1", [0.1, 0.2]), _rec("doc-2", [0.3, 0.4])]
    provider = InlineEmbeddingProvider(records)
    result = provider.get_embedding("doc-1")
    assert result is not None
    assert result.vector == [0.1, 0.2]


def test_inline_provider_returns_none_for_unembedded_document():
    records = [_rec("doc-1", None)]
    provider = InlineEmbeddingProvider(records)
    assert provider.get_embedding("doc-1") is None


def test_inline_provider_returns_none_for_unknown_id():
    provider = InlineEmbeddingProvider([_rec("doc-1", [0.1, 0.2])])
    assert provider.get_embedding("does-not-exist") is None


def test_inline_provider_len():
    provider = InlineEmbeddingProvider([_rec("doc-1", [0.1]), _rec("doc-2", None)])
    assert len(provider) == 2


def test_inline_provider_dimension_reported():
    provider = InlineEmbeddingProvider([_rec("doc-1", [0.1, 0.2, 0.3])])
    assert provider.get_embedding_dimension() == 3


def test_inline_provider_dimension_none_when_empty():
    provider = InlineEmbeddingProvider([_rec("doc-1", None)])
    assert provider.get_embedding_dimension() is None


def test_inline_provider_model_id_reported():
    provider = InlineEmbeddingProvider([_rec("doc-1", [0.1], model_id="bge-m3")])
    assert provider.model_id == "bge-m3"


def test_inline_provider_model_id_none_when_empty():
    provider = InlineEmbeddingProvider([_rec("doc-1", None)])
    assert provider.model_id is None


def test_inline_provider_rejects_mixed_embedding_models():
    records = [
        _rec("doc-1", [0.1, 0.2], model_id="bge-m3"),
        _rec("doc-2", [0.1, 0.2], model_id="e5-large"),
    ]
    with pytest.raises(ValueError):
        InlineEmbeddingProvider(records)


def test_inline_provider_ignores_unembedded_docs_when_checking_model_consistency():
    """A record with no embedding at all must not trip the mixed-model check."""
    records = [
        _rec("doc-1", [0.1, 0.2], model_id="bge-m3"),
        _rec("doc-2", None),
    ]
    provider = InlineEmbeddingProvider(records)
    assert provider.model_id == "bge-m3"