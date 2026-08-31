"""
app/core/search/semantic/engine.py

The public entry point for semantic retrieval.

    SemanticQuery(ies) -> VectorStore.search() per query -> combination
    strategy (combination.py) merges per-query results -> ranked, truncated
    -> List[SearchHit]

Single-query search is deliberately NOT a separate code path: it's just
`semantic_search()` called with a list of exactly one `SemanticQuery`.
Every combination strategy (see combination.py) is a no-op-equivalent
when there is only one query's results to "combine", so there is nothing
for a separate single-query implementation to do differently, and no
risk of the single- and multi-query paths drifting apart.

Generic-core rule: nothing in this module knows what a query vector
"means" (no field names, no domain vocabulary) -- it only knows how to
rank ids by similarity score. Turning a piece of user-facing query text
into a vector is a job for something upstream of this module (an
embedding model / a future `QueryEmbedder`-style interface), not for
`semantic_search()` itself, exactly as `EmbeddingProvider` stays out of
"how documents got embedded" (see app/core/embeddings/provider.py).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schema.search_hit import SearchHit
from app.core.search.semantic.combination import get_strategy
from app.core.search.semantic.vector_store import VectorMatch, VectorStore

# Semantic matches always match on a document's main text content -- there
# is no per-field notion of "which metadata field matched" in a pure
# vector similarity search (that's a lexical-search concept). Kept as a
# module-level constant rather than inlined so there is exactly one place
# to change it if that assumption ever needs to move into config.
_SEMANTIC_MATCHED_FIELDS = ["text"]


class SemanticQuery(BaseModel):
    """One semantic query embedding submitted to `semantic_search`.

    Deliberately just a vector + an optional weight -- this module never
    accepts raw query text, per the module docstring above.

    `weight` only affects strategies that use weights (currently
    `weighted_average`); strategies that don't (currently `max_score`)
    ignore it. Defaults to 1.0 so a caller doing single-query or
    `max_score` search never has to think about weights at all, and so
    that omitting weights on every query is equivalent to giving them all
    equal weight under `weighted_average`.
    """

    model_config = ConfigDict(extra="forbid")

    vector: list[float] = Field(..., min_length=1, description="The query embedding.")
    weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Relative weight for the weighted_average combination strategy.",
    )

    @field_validator("vector")
    @classmethod
    def vector_must_not_be_empty(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("vector must not be empty")
        return v


def semantic_search(
    vector_store: VectorStore,
    queries: Sequence[SemanticQuery],
    *,
    top_k: int,
    strategy: str = "max_score",
    candidate_pool_size: Optional[int] = None,
) -> List[SearchHit]:
    """Run one or more semantic queries against `vector_store` and return a
    ranked `List[SearchHit]`, longest at most `top_k` entries.

    Parameters
    ----------
    vector_store:
        Anything satisfying the `VectorStore` protocol. Use
        `InMemoryVectorStore` for tests or small corpora.
    queries:
        One or more `SemanticQuery` objects. A single-query search is
        just a list of length 1 -- see module docstring.
    top_k:
        Maximum number of hits to return, after combination.
    strategy:
        Name of a registered combination strategy (see combination.py).
        Defaults to `"max_score"`, matching `SemanticSearchConfig`'s
        default. Unknown names raise `ValueError` listing what's
        available.
    candidate_pool_size:
        How many candidates to pull from `vector_store` **per query**
        before combining. Defaults to `top_k`. For multi-query searches,
        callers who find that documents strong on one query but merely
        adequate on others are being pushed out before combination even
        sees them should raise this value -- that's a config/call-site
        change, not a reason to rewrite this function.

    Raises
    ------
    ValueError
        If `queries` is empty, `top_k` or `candidate_pool_size` is not
        positive, or `strategy` is not a registered strategy name.
    """
    if not queries:
        raise ValueError("semantic_search requires at least one query")
    if top_k <= 0:
        raise ValueError("top_k must be a positive integer")

    pool_size = top_k if candidate_pool_size is None else candidate_pool_size
    if pool_size <= 0:
        raise ValueError("candidate_pool_size must be a positive integer")

    combine = get_strategy(strategy)

    per_query_matches: List[List[VectorMatch]] = [
        vector_store.search(query.vector, pool_size) for query in queries
    ]
    weights = [query.weight for query in queries]

    combined_scores = combine(per_query_matches, weights)

    # Sort by score desc, tie-broken by id asc, so results are
    # deterministic regardless of dict iteration order -- the roadmap's
    # results".
    ranked = sorted(combined_scores.items(), key=lambda item: (-item[1], item[0]))

    return [
        SearchHit(id=doc_id, score=score, matched_fields=list(_SEMANTIC_MATCHED_FIELDS))
        for doc_id, score in ranked[:top_k]
    ]
