"""
app/core/search/ranking/strategies.py

This mirrors `app/core/search/semantic/combination.py`'s registry
pattern exactly, for the same reason: `engine.py` selects a strategy by
name (ultimately, `RankingConfig.strategy` from
`app/core/config/models.py`, currently a `Literal["weighted_sum"]`)
instead of hardcoding an if/else. Adding a second strategy later (e.g.
reciprocal rank fusion) means registering a new function here -- it
never requires touching `engine.py`.

Every strategy shares one signature:

    (signals: Mapping[str, SourceSignal], weights: Mapping[str, float]) -> {document_id: combined_score}

`weights` is a plain `{source_name: weight}` mapping (e.g.
`{"semantic": 0.5, "lexical": 0.5}`) rather than a dedicated config
model, so this module has no dependency on `app.core.config` -- ranking
strategies operate purely on retrieval-stage signals, and stay testable
without constructing a full use-case config.
"""
from __future__ import annotations

from typing import Callable, Dict, Mapping, Optional

from pydantic import BaseModel, ConfigDict


class SourceSignal(BaseModel):
    """Everything one ranking strategy needs to know about a single
    document id, gathered from each retrieval source that ran.

    Deliberately a flat two-field shape today (matching the two sources
    that exist -- semantic and lexical) rather than an open-ended dict;
    if a third retrieval source is added later, it gets its own field
    here plus a case in whatever strategy wants to use it, same as any
    other schema change -- this is not the extension seam (the strategy
    *registry* below is); it's simply the agreed input contract every
    strategy receives today.
    """

    model_config = ConfigDict(extra="forbid")

    semantic_score: Optional[float] = None
    lexical_matched: bool = False


RankingStrategy = Callable[[Mapping[str, SourceSignal], Mapping[str, float]], Dict[str, float]]

_STRATEGIES: Dict[str, RankingStrategy] = {}


def register_strategy(name: str) -> Callable[[RankingStrategy], RankingStrategy]:
    """Decorator registering a ranking strategy under `name`. Raises if
    `name` is already registered, for the same reason
    `combination.py::register_strategy` does: two strategies silently
    fighting over one name would make config-driven selection depend on
    import order.
    """

    def decorator(fn: RankingStrategy) -> RankingStrategy:
        if name in _STRATEGIES:
            raise ValueError(f"ranking strategy '{name}' is already registered")
        _STRATEGIES[name] = fn
        return fn

    return decorator


def get_strategy(name: str) -> RankingStrategy:
    """Look up a registered ranking strategy by name. Raises `ValueError`
    (not `KeyError`) with the available strategies listed, so a bad
    `search.ranking.strategy` config value reads like a config error.
    """
    try:
        return _STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"unknown ranking strategy '{name}'. Available strategies: {available_strategies()}"
        ) from None


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)


@register_strategy("weighted_sum")
def weighted_sum(
    signals: Mapping[str, SourceSignal],
    weights: Mapping[str, float],
) -> Dict[str, float]:
    """`score = weights["semantic"] * semantic_score + weights["lexical"] * lexical_indicator`.

    `lexical_indicator` is `1.0` if the document was among the lexical
    hits, `0.0` otherwise -- lexical retrieval is a boolean match with no
    relevance score of its own (`SearchHit.score is None`, see
    `app/core/search/lexical/engine.py`), so it can only contribute to a
    weighted sum as a present/absent signal, not a continuous one. A
    document with no semantic score (it wasn't a semantic hit)
    contributes `0.0` for that term rather than being excluded.

    Assumes `semantic_score` values are already in a range where summing
    them against a `[0, 1]`-ish lexical indicator is meaningful (e.g.
    cosine similarity, or a use-case-specific normalization applied
    upstream) -- this function does not renormalize scores itself; see
    docs/ranking.md for why that's a deliberate scope boundary here.

    Raises if every weight is non-positive, matching
    `RankingConfig.weights_not_both_zero`'s reasoning: a ranking that
    can never produce a non-zero score for anything is a config error,
    not a valid (if useless) ranking.
    """
    if sum(weights.values()) <= 0:
        raise ValueError("weighted_sum requires at least one positive weight")

    combined: Dict[str, float] = {}
    for doc_id, signal in signals.items():
        semantic_component = (signal.semantic_score or 0.0) * weights.get("semantic", 0.0)
        lexical_component = (1.0 if signal.lexical_matched else 0.0) * weights.get("lexical", 0.0)
        combined[doc_id] = semantic_component + lexical_component
    return combined
