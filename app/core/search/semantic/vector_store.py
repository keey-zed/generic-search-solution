"""
app/core/search/semantic/vector_store.py

The interface semantic retrieval is allowed to depend on for
"given a query vector, which document ids are closest, and how close".

Mirrors the pattern already established by
`app/core/embeddings/provider.py` (`EmbeddingProvider` /
`InlineEmbeddingProvider`) deliberately, and is a DIFFERENT concern from
it:

    EmbeddingProvider  -> "what is THIS document's own embedding?"        (lookup by id)
    VectorStore        -> "which document ids are closest to THIS query?" (similarity search)

Semantic retrieval code must only ever call `VectorStore.search()`. It
must never assume the store is FAISS, a hosted vector DB, or an
in-memory dict -- that indirection is what lets a real project swap in
FAISS/pgvector/etc. later by writing one new class, with zero changes to
`engine.py`. `InMemoryVectorStore` below is the only implementation that
exists today, and it is intentionally pure Python (no numpy/faiss/etc.)
so that unit tests for this module never depend on infra, per the
roadmap's Definition of Done for this deliverable.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Protocol, Sequence, Tuple, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VectorMatch(BaseModel):
    """One raw similarity hit coming directly out of a `VectorStore`,
    before any cross-query combination (combination.py) or conversion
    into a `SearchHit` (engine.py) happens.

    Deliberately minimal -- an id and a score, nothing else. A
    `VectorStore` implementation does not know about documents' text or
    metadata; joining a match back to its full record is a job for
    whatever calls this module, not for the store itself.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Matches a DocumentRecord.id.")
    score: float = Field(..., description="Similarity score; higher means more similar.")

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must not be blank or whitespace-only")
        return v

    @field_validator("score")
    @classmethod
    def score_must_be_finite(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("score must be a finite number, not NaN/Inf")
        return v


@runtime_checkable
class VectorStore(Protocol):
    """Anything semantic retrieval can ask "which ids are closest to this
    query vector". `Protocol`, not a base class -- any object with a
    matching `search` method satisfies it, no inheritance required
    (same reasoning as `EmbeddingProvider`).
    """

    def search(self, query_vector: Sequence[float], top_k: int) -> List[VectorMatch]:
        """Return up to `top_k` nearest matches to `query_vector`, sorted
        by `score` descending (most similar first).

        Implementations must not raise merely because the store holds
        fewer than `top_k` vectors -- return as many as are available. A
        dimension mismatch between `query_vector` and the store's stored
        vectors IS an error and should raise (a silently-wrong similarity
        score is worse than a loud failure).
        """
        ...


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two vectors, in [-1, 1].

    A zero vector has no well-defined direction, so similarity against
    one is defined as 0.0 (neutral) rather than raising or dividing by
    zero -- this can only happen with a deliberately-degenerate input
    (e.g. a placeholder all-zero embedding), and 0.0 keeps it from either
    crashing retrieval or masquerading as a strong match.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


class InMemoryVectorStore:
    """Fake/in-memory `VectorStore`: brute-force cosine similarity over a
    dict of id -> vector held in memory.

    This exists for two reasons:
      1. It's the "small fake vector store" the roadmap asks for, so unit
         tests for semantic retrieval never depend on FAISS or any other
         infra.
      2. It's a perfectly usable real implementation for small corpora --
         nothing about it is test-only code masquerading as production
         code; it's simply the naive baseline that a FAISS-backed (or
         other) `VectorStore` would later replace for scale.
    """

    def __init__(self, vectors: Iterable[Tuple[str, Sequence[float]]] | None = None):
        self._vectors: dict[str, list[float]] = {}
        for id_, vector in vectors or []:
            self.add(id_, vector)

    def add(self, id_: str, vector: Sequence[float]) -> None:
        if not id_ or not id_.strip():
            raise ValueError("id must not be blank or whitespace-only")
        vec = list(vector)
        if not vec:
            raise ValueError(f"vector for id '{id_}' must not be empty")
        self._vectors[id_] = vec

    def __len__(self) -> int:
        return len(self._vectors)

    def search(self, query_vector: Sequence[float], top_k: int) -> List[VectorMatch]:
        if top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        scored: list[VectorMatch] = []
        for id_, vec in self._vectors.items():
            try:
                score = cosine_similarity(query_vector, vec)
            except ValueError as exc:
                raise ValueError(
                    f"query vector incompatible with stored vector for id '{id_}': {exc}"
                ) from exc
            scored.append(VectorMatch(id=id_, score=score))

        # Sort by score desc; break ties by id so results are deterministic
        # regardless of dict insertion order.
        scored.sort(key=lambda m: (-m.score, m.id))
        return scored[:top_k]
