"""
app/core/embeddings/provider.py

The standard interface retrieval calls to obtain a document's embedding.

Conceptually (source doc's Phase 0 deliverable 2):

    Retrieval -> EmbeddingProvider -> InlineEmbeddingProvider -> EmbeddedDocumentRecord   (V1, this file)
                                    -> (future) a separate embeddings store / vector DB    (not built yet)

Retrieval code should only ever call `EmbeddingProvider.get_embedding()`
-- never reach into `EmbeddedDocumentRecord` or any other storage detail
directly. That indirection is the entire point: swapping V1's inline
storage for a dedicated embeddings table or a vector DB later means
writing a new class that satisfies `EmbeddingProvider` and wiring it in
at startup, with zero changes to retrieval code. Do not build that
alternative implementation now -- v0 ships exactly one, `InlineEmbeddingProvider`.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Anything retrieval can ask "what's the embedding for this document id".

    Deliberately minimal: one lookup key (document id), one optional
    return value. A provider backed by an in-memory dict (v0), a
    dedicated embeddings table, or a vector DB must all be able to
    implement this without retrieval code knowing which one it's talking
    to.
    """

    def get_embedding(self, document_id: str) -> Optional[Embedding]:
        """Return the embedding for `document_id`.

        Returns None when the document has no embedding yet (not
        embedded, embedding job pending, deliberately text-only record,
        or an id the provider doesn't know about at all). None is a
        normal, expected outcome for retrieval to handle -- not an
        error condition, and implementations must not raise for a
        missing/unembedded document.
        """
        ...


class InlineEmbeddingProvider:
    """V1 implementation: embeddings live directly on EmbeddedDocumentRecord.

    Built once from an iterable of EmbeddedDocumentRecord (e.g. everything
    currently loaded into memory for a corpus); lookups are O(1) after
    that.

    Consistency check: all non-None embeddings supplied at construction
    time must share the same `model_id`. A provider silently mixing
    vectors from two different embedding models would make any
    similarity computation over it meaningless without any visible
    error, so this is checked eagerly (fail at load time, not deep inside
    a later similarity search).
    """

    def __init__(self, records: Iterable[EmbeddedDocumentRecord]):
        by_id: dict[str, Optional[Embedding]] = {}
        seen_model_id: Optional[str] = None

        for record in records:
            by_id[record.id] = record.embedding
            if record.embedding is not None:
                if seen_model_id is None:
                    seen_model_id = record.embedding.model_id
                elif record.embedding.model_id != seen_model_id:
                    raise ValueError(
                        "InlineEmbeddingProvider received embeddings from "
                        f"multiple models ('{seen_model_id}' and "
                        f"'{record.embedding.model_id}', seen at document "
                        f"'{record.id}'). Mixing embedding models in one "
                        "provider produces meaningless similarity scores -- "
                        "build a separate provider per model instead."
                    )

        self._by_id = by_id
        self._model_id = seen_model_id

    def get_embedding(self, document_id: str) -> Optional[Embedding]:
        return self._by_id.get(document_id)

    @property
    def model_id(self) -> Optional[str]:
        """The single embedding model_id shared by all stored embeddings,
        or None if this provider has no embeddings at all yet."""
        return self._model_id

    def get_embedding_dimension(self) -> Optional[int]:
        """The vector dimensionality shared by all stored embeddings, or
        None if none are present yet. Lets retrieval fail fast on a
        mismatched query-vector dimension instead of discovering the
        mismatch deep inside a similarity computation."""
        for embedding in self._by_id.values():
            if embedding is not None:
                return embedding.dim
        return None

    def __len__(self) -> int:
        return len(self._by_id)