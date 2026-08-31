"""
app/core/search/ranking/engine.py

The public entry point that merges a semantic result set and a lexical result set into
one ranked `List[SearchHit]`.

    semantic_hits, lexical_hits
          |
          v
    per-id SourceSignal (strategies.py) -- which source(s) hit this id, and how
          |
          v
    named ranking strategy (strategies.py registry) -> {id: combined_score}
          |
          v
    sort desc by score, tie-break by id
          |
          v
    List[SearchHit] (id, combined score, merged matched_fields/snippet/metadata)

A document is included if EITHER source returned it -- this is a union,
not an intersection. Requiring both sources to agree is a stricter
policy a project could implement as a different ranking strategy (e.g.
one that returns a score of 0/exclusion for any id missing from either
`signals` source), not something `merge_and_rank` bakes in by default.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from app.core.schema.metadata_types import TypedMetadataValue
from app.core.schema.search_hit import SearchHit, Snippet
from app.core.search.ranking.strategies import SourceSignal, get_strategy

# Matches RankingWeights' defaults in app/core/config/models.py. Kept as
# a local constant (rather than importing that config model) so this
# module has no dependency on app.core.config -- see strategies.py's
# module docstring for why ranking stays decoupled from config.
DEFAULT_WEIGHTS: Dict[str, float] = {"semantic": 0.5, "lexical": 0.5}


def _merge_matched_fields(a: Sequence[str], b: Sequence[str]) -> List[str]:
    """Union, preserving first-seen order, deduplicated."""
    merged: List[str] = list(a)
    for field in b:
        if field not in merged:
            merged.append(field)
    return merged


def _merge_snippet(a: Optional[Snippet], b: Optional[Snippet]) -> Optional[Snippet]:
    """Prefer whichever source has one; arbitrary but deterministic when
    both do (semantic's wins) since there is no principled way to prefer
    one over the other in the general case.
    """
    return a if a is not None else b


def _merge_metadata(
    a: Mapping[str, TypedMetadataValue], b: Mapping[str, TypedMetadataValue]
) -> Dict[str, TypedMetadataValue]:
    """Union of both sources' metadata; on a key present in both, `a`
    (semantic) wins -- an arbitrary but deterministic tie-break. In
    practice both `semantic_search()` and `lexical_search()` currently
    return `metadata={}` (enriching a hit with metadata is the API
    layer's job, not retrieval's -- see their docstrings), so this
    rarely matters today; it exists so `merge_and_rank` has well-defined
    behavior once a retrieval source does start attaching metadata.
    """
    merged = dict(b)
    merged.update(a)
    return merged


def merge_and_rank(
    semantic_hits: Sequence[SearchHit],
    lexical_hits: Sequence[SearchHit],
    *,
    strategy: str = "weighted_sum",
    weights: Optional[Mapping[str, float]] = None,
) -> List[SearchHit]:
    """Merge `semantic_hits` and `lexical_hits` into one ranked
    `List[SearchHit]`.

    Parameters
    ----------
    semantic_hits, lexical_hits:
        Typically the outputs of `semantic_search()`
        (`app/core/search/semantic/engine.py`) and `lexical_search()`
        (`app/core/search/lexical/engine.py`), respectively. Either may
        be empty (e.g. a use case with `search.lexical.enabled: false`
        never runs lexical retrieval at all) -- ranking over a single
        source degrades gracefully rather than requiring both.
    strategy:
        Name of a registered ranking strategy (see `strategies.py`).
        Defaults to `"weighted_sum"`, matching `RankingConfig`'s only
        strategy today. Unknown names raise `ValueError` listing what's
        available -- this is the seam the roadmap asks for: adding a
        second strategy is "register it in strategies.py," never a
        change here.
    weights:
        A `{source_name: weight}` mapping, e.g. `{"semantic": 0.7,
        "lexical": 0.3}`. Defaults to `DEFAULT_WEIGHTS` (0.5/0.5,
        matching `RankingWeights`'s own defaults). Strategies that don't
        use weights are free to ignore this parameter, same as
        `combination.py`'s `max_score` ignores its `weights` argument.

    Returns
    -------
    A `List[SearchHit]`, one per document id appearing in EITHER input,
    sorted by combined score descending (ties broken by id ascending for
    determinism), with `score` replaced by the strategy's combined score
    and `matched_fields`/`snippet`/`metadata` reconciled across sources
    (see the `_merge_*` helpers above).
    """
    resolved_weights = DEFAULT_WEIGHTS if weights is None else weights
    combine = get_strategy(strategy)

    semantic_by_id = {hit.id: hit for hit in semantic_hits}
    lexical_by_id = {hit.id: hit for hit in lexical_hits}
    all_ids = set(semantic_by_id) | set(lexical_by_id)

    signals: Dict[str, SourceSignal] = {
        doc_id: SourceSignal(
            semantic_score=semantic_by_id[doc_id].score if doc_id in semantic_by_id else None,
            lexical_matched=doc_id in lexical_by_id,
        )
        for doc_id in all_ids
    }

    combined_scores = combine(signals, resolved_weights)

    ranked_ids = sorted(combined_scores.items(), key=lambda item: (-item[1], item[0]))

    merged_hits: List[SearchHit] = []
    for doc_id, score in ranked_ids:
        s_hit = semantic_by_id.get(doc_id)
        l_hit = lexical_by_id.get(doc_id)

        matched_fields = _merge_matched_fields(
            s_hit.matched_fields if s_hit else [],
            l_hit.matched_fields if l_hit else [],
        )
        snippet = _merge_snippet(
            s_hit.snippet if s_hit else None,
            l_hit.snippet if l_hit else None,
        )
        metadata = _merge_metadata(
            s_hit.metadata if s_hit else {},
            l_hit.metadata if l_hit else {},
        )

        merged_hits.append(
            SearchHit(
                id=doc_id,
                score=score,
                matched_fields=matched_fields,
                snippet=snippet,
                metadata=metadata,
            )
        )

    return merged_hits
