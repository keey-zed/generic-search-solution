import pytest

from app.core.schema.search_hit import SearchHit, Snippet
from app.core.search.ranking.engine import DEFAULT_WEIGHTS, merge_and_rank
from app.core.search.ranking.strategies import (
    SourceSignal,
    available_strategies,
    get_strategy,
    register_strategy,
    weighted_sum,
)


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------


def test_available_strategies_includes_weighted_sum():
    assert "weighted_sum" in available_strategies()


def test_get_strategy_unknown_name_raises_value_error():
    with pytest.raises(ValueError):
        get_strategy("does-not-exist")


def test_register_strategy_rejects_duplicate_name():
    with pytest.raises(ValueError):
        @register_strategy("weighted_sum")
        def _dup(signals, weights):
            return {}


def test_seam_supports_a_second_strategy_with_no_engine_changes():
    """Demonstrates the pluggability the roadmap asks for: a brand-new
    strategy can be registered and selected by name, with zero changes
    to merge_and_rank / engine.py.
    """

    @register_strategy("_test_semantic_only")
    def _semantic_only(signals, weights):
        return {doc_id: (sig.semantic_score or 0.0) for doc_id, sig in signals.items()}

    semantic_hits = [SearchHit(id="a", score=0.9), SearchHit(id="b", score=0.1)]
    lexical_hits = [SearchHit(id="b", score=None)]  # would normally boost "b"

    hits = merge_and_rank(semantic_hits, lexical_hits, strategy="_test_semantic_only")
    # Under this strategy lexical presence is completely ignored, so "a"
    # (higher semantic score) still outranks "b" despite "b" also being
    # a lexical hit.
    assert [h.id for h in hits] == ["a", "b"]


# ---------------------------------------------------------------------------
# weighted_sum strategy (unit-level, via SourceSignal directly)
# ---------------------------------------------------------------------------


def test_weighted_sum_combines_semantic_and_lexical():
    signals = {
        "a": SourceSignal(semantic_score=0.8, lexical_matched=True),
        "b": SourceSignal(semantic_score=0.8, lexical_matched=False),
    }
    combined = weighted_sum(signals, {"semantic": 0.5, "lexical": 0.5})
    # "a" gets the lexical bonus, "b" doesn't.
    assert combined["a"] == pytest.approx(0.5 * 0.8 + 0.5 * 1.0)
    assert combined["b"] == pytest.approx(0.5 * 0.8 + 0.5 * 0.0)
    assert combined["a"] > combined["b"]


def test_weighted_sum_missing_semantic_score_counts_as_zero():
    signals = {"a": SourceSignal(semantic_score=None, lexical_matched=True)}
    combined = weighted_sum(signals, {"semantic": 0.5, "lexical": 0.5})
    assert combined["a"] == pytest.approx(0.5)


def test_weighted_sum_respects_custom_weights():
    signals = {"a": SourceSignal(semantic_score=1.0, lexical_matched=False)}
    combined = weighted_sum(signals, {"semantic": 1.0, "lexical": 0.0})
    assert combined["a"] == pytest.approx(1.0)


def test_weighted_sum_ignores_unknown_weight_keys():
    signals = {"a": SourceSignal(semantic_score=1.0, lexical_matched=True)}
    combined = weighted_sum(signals, {"semantic": 0.5, "lexical": 0.5, "future_source": 999})
    assert combined["a"] == pytest.approx(1.0)


def test_weighted_sum_rejects_all_non_positive_weights():
    signals = {"a": SourceSignal(semantic_score=1.0, lexical_matched=True)}
    with pytest.raises(ValueError):
        weighted_sum(signals, {"semantic": 0.0, "lexical": 0.0})


# ---------------------------------------------------------------------------
# merge_and_rank end to end
# ---------------------------------------------------------------------------


def test_merge_and_rank_unions_both_sources():
    semantic_hits = [SearchHit(id="a", score=0.9)]
    lexical_hits = [SearchHit(id="b", score=None)]
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert {h.id for h in hits} == {"a", "b"}


def test_merge_and_rank_document_in_both_sources_ranks_higher():
    semantic_hits = [SearchHit(id="a", score=0.6), SearchHit(id="b", score=0.6)]
    lexical_hits = [SearchHit(id="a", score=None)]  # only "a" also matches lexically
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert hits[0].id == "a"
    assert hits[0].score > hits[1].score


def test_merge_and_rank_semantic_only_input():
    semantic_hits = [SearchHit(id="a", score=0.9), SearchHit(id="b", score=0.1)]
    hits = merge_and_rank(semantic_hits, [])
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(0.9 * DEFAULT_WEIGHTS["semantic"])


def test_merge_and_rank_lexical_only_input():
    lexical_hits = [SearchHit(id="a", score=None), SearchHit(id="b", score=None)]
    hits = merge_and_rank([], lexical_hits)
    assert {h.id for h in hits} == {"a", "b"}
    for h in hits:
        assert h.score == pytest.approx(DEFAULT_WEIGHTS["lexical"])


def test_merge_and_rank_both_empty_returns_empty_list():
    assert merge_and_rank([], []) == []


def test_merge_and_rank_custom_weights():
    semantic_hits = [SearchHit(id="a", score=1.0)]
    lexical_hits = [SearchHit(id="b", score=None)]
    hits = merge_and_rank(
        semantic_hits, lexical_hits, weights={"semantic": 1.0, "lexical": 0.0}
    )
    scores = {h.id: h.score for h in hits}
    assert scores["a"] == pytest.approx(1.0)
    assert scores["b"] == pytest.approx(0.0)


def test_merge_and_rank_unknown_strategy_raises():
    with pytest.raises(ValueError):
        merge_and_rank([SearchHit(id="a", score=1.0)], [], strategy="does-not-exist")


def test_merge_and_rank_deterministic_tie_break_by_id():
    # "a" and "b" get identical combined scores under default weights.
    semantic_hits = [SearchHit(id="b", score=0.5), SearchHit(id="a", score=0.5)]
    hits = merge_and_rank(semantic_hits, [])
    assert [h.id for h in hits] == ["a", "b"]


def test_merge_and_rank_is_deterministic_across_repeated_calls():
    semantic_hits = [SearchHit(id="a", score=0.7), SearchHit(id="c", score=0.3)]
    lexical_hits = [SearchHit(id="b", score=None), SearchHit(id="c", score=None)]
    first = merge_and_rank(semantic_hits, lexical_hits)
    second = merge_and_rank(semantic_hits, lexical_hits)
    assert [h.id for h in first] == [h.id for h in second]
    assert [h.score for h in first] == [h.score for h in second]


# ---------------------------------------------------------------------------
# Field reconciliation (matched_fields / snippet / metadata)
# ---------------------------------------------------------------------------


def test_merge_and_rank_merges_matched_fields_deduplicated():
    semantic_hits = [SearchHit(id="a", score=0.5, matched_fields=["text"])]
    lexical_hits = [SearchHit(id="a", score=None, matched_fields=["text", "title"])]
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert hits[0].matched_fields == ["text", "title"]


def test_merge_and_rank_prefers_semantic_snippet_when_both_present():
    snippet_a = Snippet(text="semantic snippet")
    snippet_b = Snippet(text="lexical snippet")
    semantic_hits = [SearchHit(id="a", score=0.5, snippet=snippet_a)]
    lexical_hits = [SearchHit(id="a", score=None, snippet=snippet_b)]
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert hits[0].snippet.text == "semantic snippet"


def test_merge_and_rank_falls_back_to_lexical_snippet_when_semantic_has_none():
    snippet_b = Snippet(text="lexical snippet")
    semantic_hits = [SearchHit(id="a", score=0.5)]
    lexical_hits = [SearchHit(id="a", score=None, snippet=snippet_b)]
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert hits[0].snippet.text == "lexical snippet"


def test_merge_and_rank_merges_metadata_semantic_wins_conflicts():
    semantic_hits = [SearchHit(id="a", score=0.5, metadata={"doctype": "decree", "shared": "from_semantic"})]
    lexical_hits = [SearchHit(id="a", score=None, metadata={"author": "someone", "shared": "from_lexical"})]
    hits = merge_and_rank(semantic_hits, lexical_hits)
    assert hits[0].metadata == {
        "doctype": "decree",
        "author": "someone",
        "shared": "from_semantic",
    }
