"""
app/core/search/semantic/combination.py

"The engine should also support multiple semantic queries ... the results from these queries can
subsequently be combined or ranked according to the required logic."

The roadmap is explicit that this must be **at least two strategies
behind a configurable strategy name -- don't hardcode one**. Concretely,
`docs/config-schema.md` and `SemanticSearchConfig.multi_query_combination`
already fix the two names a v0 project config can select:

    max_score        | weighted_average

This module owns exactly that seam: a small registry mapping a strategy
name to a combination function, so `engine.py` (and, later, the YAML
config loader) select a strategy by string instead of the module
hardcoding an if/else. Adding a third strategy later means registering a
new function here -- it never requires touching `engine.py`.

Every strategy shares one signature so callers don't need to know which
strategy they're calling:

    (per_query_matches, weights) -> {document_id: combined_score}

`weights` is always passed, even to strategies that ignore it (e.g.
`max_score`) -- a uniform signature is what lets `engine.py` call
whichever strategy the config named without a strategy-specific branch.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Sequence

from app.core.search.semantic.vector_store import VectorMatch

CombinationStrategy = Callable[[Sequence[List[VectorMatch]], Sequence[float]], Dict[str, float]]

_STRATEGIES: Dict[str, CombinationStrategy] = {}


def register_strategy(name: str) -> Callable[[CombinationStrategy], CombinationStrategy]:
    """Decorator registering a combination strategy under `name`.

    Raises if `name` is already registered -- two strategies silently
    fighting over one name would make config-driven strategy selection
    non-deterministic depending on import order, which is worse than
    failing loudly at import time.
    """

    def decorator(fn: CombinationStrategy) -> CombinationStrategy:
        if name in _STRATEGIES:
            raise ValueError(f"combination strategy '{name}' is already registered")
        _STRATEGIES[name] = fn
        return fn

    return decorator


def get_strategy(name: str) -> CombinationStrategy:
    """Look up a registered combination strategy by name.

    Raises `ValueError` (not `KeyError`) for an unknown name, with the
    list of available strategies in the message -- this is the error a
    bad `search.semantic.multi_query_combination` config value should
    surface, so it should read like a config error, not an internal
    lookup failure.
    """
    try:
        return _STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"unknown semantic multi-query combination strategy '{name}'. "
            f"Available strategies: {available_strategies()}"
        ) from None


def available_strategies() -> List[str]:
    return sorted(_STRATEGIES)


@register_strategy("max_score")
def combine_max_score(
    per_query_matches: Sequence[List[VectorMatch]],
    weights: Sequence[float],
) -> Dict[str, float]:
    """For each document id, keep the highest score it received across
    any of the queries.

    This is the right default when queries express alternative phrasings
    of "the same intent" (e.g. a query translated two ways) -- a document
    that matches strongly on *any one* phrasing should rank highly, even
    if it barely matched the others. `weights` is accepted for signature
    uniformity with other strategies but is not used here.
    """
    combined: Dict[str, float] = {}
    for matches in per_query_matches:
        for match in matches:
            if match.id not in combined or match.score > combined[match.id]:
                combined[match.id] = match.score
    return combined


@register_strategy("weighted_average")
def combine_weighted_average(
    per_query_matches: Sequence[List[VectorMatch]],
    weights: Sequence[float],
) -> Dict[str, float]:
    """For each document id, compute the weighted mean of its score across
    all queries.

    This is the right choice when queries express genuinely different
    facets that should all contribute (e.g. one query per required
    aspect of a request) -- a document strong on only one facet is
    penalized relative to one that's consistently relevant across all of
    them.

    A document absent from a given query's result set (it wasn't among
    that query's top candidates) contributes a score of 0.0 for that
    query, rather than being excluded from the average or treated as
    missing data -- "didn't show up as a close match" is itself
    informative and should pull the average down, not be ignored.

    Raises if `weights` has a different length than `per_query_matches`,
    or if all weights are non-positive (an all-zero weighted average is
    undefined, not silently 0-for-everyone).
    """
    if len(weights) != len(per_query_matches):
        raise ValueError(
            "weights must have the same length as per_query_matches "
            f"({len(weights)} != {len(per_query_matches)})"
        )
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ValueError("sum of weights must be > 0 for the weighted_average strategy")

    score_maps: List[Dict[str, float]] = [
        {match.id: match.score for match in matches} for matches in per_query_matches
    ]
    all_ids = set().union(*score_maps) if score_maps else set()

    combined: Dict[str, float] = {}
    for doc_id in all_ids:
        weighted_sum = sum(
            score_maps[i].get(doc_id, 0.0) * weights[i] for i in range(len(weights))
        )
        combined[doc_id] = weighted_sum / total_weight
    return combined
