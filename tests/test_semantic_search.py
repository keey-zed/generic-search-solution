import math

import pytest
from pydantic import ValidationError

from app.core.schema.search_hit import SearchHit
from app.core.search.semantic.combination import (
    combine_max_score,
    combine_weighted_average,
    get_strategy,
    available_strategies,
    register_strategy,
)
from app.core.search.semantic.engine import SemanticQuery, semantic_search
from app.core.search.semantic.vector_store import (
    InMemoryVectorStore,
    VectorMatch,
    VectorStore,
    cosine_similarity,
)


# ---------------------------------------------------------------------------
# VectorMatch
# ---------------------------------------------------------------------------


def test_vector_match_rejects_blank_id():
    with pytest.raises(ValidationError):
        VectorMatch(id="   ", score=0.5)


def test_vector_match_rejects_nan_score():
    with pytest.raises(ValidationError):
        VectorMatch(id="doc-1", score=float("nan"))


def test_vector_match_rejects_inf_score():
    with pytest.raises(ValidationError):
        VectorMatch(id="doc-1", score=float("inf"))


def test_vector_match_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        VectorMatch(id="doc-1", score=0.5, rank=1)


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_opposite_vectors_is_minus_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_defined_as_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_dimension_mismatch_raises():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# InMemoryVectorStore
# ---------------------------------------------------------------------------


def test_in_memory_store_satisfies_vector_store_protocol():
    store = InMemoryVectorStore()
    assert isinstance(store, VectorStore)


def test_in_memory_store_search_ranks_by_similarity_desc():
    store = InMemoryVectorStore(
        [
            ("far", [0.0, 1.0]),
            ("near", [1.0, 0.0]),
            ("mid", [0.7, 0.7]),
        ]
    )
    results = store.search([1.0, 0.0], top_k=3)
    assert [m.id for m in results] == ["near", "mid", "far"]


def test_in_memory_store_search_respects_top_k():
    store = InMemoryVectorStore([("a", [1.0, 0.0]), ("b", [0.9, 0.1]), ("c", [0.0, 1.0])])
    results = store.search([1.0, 0.0], top_k=2)
    assert len(results) == 2
    assert [m.id for m in results] == ["a", "b"]


def test_in_memory_store_search_top_k_larger_than_store_returns_all():
    store = InMemoryVectorStore([("a", [1.0, 0.0])])
    results = store.search([1.0, 0.0], top_k=50)
    assert len(results) == 1


def test_in_memory_store_search_empty_store_returns_empty_list():
    store = InMemoryVectorStore()
    assert store.search([1.0, 0.0], top_k=5) == []


def test_in_memory_store_search_rejects_non_positive_top_k():
    store = InMemoryVectorStore([("a", [1.0, 0.0])])
    with pytest.raises(ValueError):
        store.search([1.0, 0.0], top_k=0)


def test_in_memory_store_search_rejects_dimension_mismatch():
    store = InMemoryVectorStore([("a", [1.0, 0.0, 0.0])])
    with pytest.raises(ValueError):
        store.search([1.0, 0.0], top_k=1)


def test_in_memory_store_add_rejects_blank_id():
    store = InMemoryVectorStore()
    with pytest.raises(ValueError):
        store.add("   ", [1.0, 0.0])


def test_in_memory_store_add_rejects_empty_vector():
    store = InMemoryVectorStore()
    with pytest.raises(ValueError):
        store.add("a", [])


def test_in_memory_store_len():
    store = InMemoryVectorStore([("a", [1.0]), ("b", [2.0])])
    assert len(store) == 2


def test_in_memory_store_deterministic_tie_break_by_id():
    # "a" and "b" are equidistant from the query -- tie must break by id.
    store = InMemoryVectorStore([("b", [1.0, 0.0]), ("a", [1.0, 0.0])])
    results = store.search([1.0, 0.0], top_k=2)
    assert [m.id for m in results] == ["a", "b"]


# ---------------------------------------------------------------------------
# Combination strategy registry
# ---------------------------------------------------------------------------


def test_available_strategies_includes_both_required_strategies():
    assert {"max_score", "weighted_average"}.issubset(set(available_strategies()))


def test_get_strategy_unknown_name_raises_value_error():
    with pytest.raises(ValueError):
        get_strategy("does-not-exist")


def test_get_strategy_returns_callable():
    assert callable(get_strategy("max_score"))
    assert callable(get_strategy("weighted_average"))


def test_register_strategy_rejects_duplicate_name():
    with pytest.raises(ValueError):
        @register_strategy("max_score")
        def _dup(per_query_matches, weights):
            return {}


def test_combine_max_score_keeps_highest_per_document():
    q1 = [VectorMatch(id="a", score=0.9), VectorMatch(id="b", score=0.2)]
    q2 = [VectorMatch(id="a", score=0.4), VectorMatch(id="b", score=0.8)]
    combined = combine_max_score([q1, q2], weights=[1.0, 1.0])
    assert combined == {"a": pytest.approx(0.9), "b": pytest.approx(0.8)}


def test_combine_max_score_document_only_in_one_query():
    q1 = [VectorMatch(id="a", score=0.5)]
    q2 = [VectorMatch(id="b", score=0.7)]
    combined = combine_max_score([q1, q2], weights=[1.0, 1.0])
    assert combined == {"a": pytest.approx(0.5), "b": pytest.approx(0.7)}


def test_combine_weighted_average_equal_weights_is_plain_mean():
    q1 = [VectorMatch(id="a", score=1.0)]
    q2 = [VectorMatch(id="a", score=0.0)]
    combined = combine_weighted_average([q1, q2], weights=[1.0, 1.0])
    assert combined["a"] == pytest.approx(0.5)


def test_combine_weighted_average_respects_unequal_weights():
    q1 = [VectorMatch(id="a", score=1.0)]
    q2 = [VectorMatch(id="a", score=0.0)]
    # 3x weight on q1 vs 1x on q2 -> (1.0*3 + 0.0*1) / 4 = 0.75
    combined = combine_weighted_average([q1, q2], weights=[3.0, 1.0])
    assert combined["a"] == pytest.approx(0.75)


def test_combine_weighted_average_missing_document_counts_as_zero():
    q1 = [VectorMatch(id="a", score=1.0)]
    q2: list[VectorMatch] = []  # "a" did not appear among q2's candidates
    combined = combine_weighted_average([q1, q2], weights=[1.0, 1.0])
    assert combined["a"] == pytest.approx(0.5)


def test_combine_weighted_average_rejects_mismatched_weights_length():
    q1 = [VectorMatch(id="a", score=1.0)]
    with pytest.raises(ValueError):
        combine_weighted_average([q1], weights=[1.0, 1.0])


def test_combine_weighted_average_rejects_all_zero_weights():
    q1 = [VectorMatch(id="a", score=1.0)]
    q2 = [VectorMatch(id="a", score=0.0)]
    with pytest.raises(ValueError):
        combine_weighted_average([q1, q2], weights=[0.0, 0.0])


# ---------------------------------------------------------------------------
# SemanticQuery
# ---------------------------------------------------------------------------


def test_semantic_query_default_weight_is_one():
    q = SemanticQuery(vector=[0.1, 0.2])
    assert q.weight == 1.0


def test_semantic_query_rejects_empty_vector():
    with pytest.raises(ValidationError):
        SemanticQuery(vector=[])


def test_semantic_query_rejects_negative_weight():
    with pytest.raises(ValidationError):
        SemanticQuery(vector=[0.1], weight=-1.0)


def test_semantic_query_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        SemanticQuery(vector=[0.1], text="hello")


# ---------------------------------------------------------------------------
# semantic_search (end to end, single- and multi-query)
# ---------------------------------------------------------------------------


def _store():
    return InMemoryVectorStore(
        [
            ("near", [1.0, 0.0]),
            ("mid", [0.7, 0.7]),
            ("far", [0.0, 1.0]),
        ]
    )


def test_semantic_search_single_query_returns_search_hits():
    hits = semantic_search(_store(), [SemanticQuery(vector=[1.0, 0.0])], top_k=3)
    assert all(isinstance(h, SearchHit) for h in hits)
    assert [h.id for h in hits] == ["near", "mid", "far"]


def test_semantic_search_matched_fields_defaults_to_text():
    hits = semantic_search(_store(), [SemanticQuery(vector=[1.0, 0.0])], top_k=1)
    assert hits[0].matched_fields == ["text"]


def test_semantic_search_respects_top_k():
    hits = semantic_search(_store(), [SemanticQuery(vector=[1.0, 0.0])], top_k=1)
    assert len(hits) == 1
    assert hits[0].id == "near"


def test_semantic_search_rejects_empty_queries():
    with pytest.raises(ValueError):
        semantic_search(_store(), [], top_k=3)


def test_semantic_search_rejects_non_positive_top_k():
    with pytest.raises(ValueError):
        semantic_search(_store(), [SemanticQuery(vector=[1.0, 0.0])], top_k=0)


def test_semantic_search_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        semantic_search(
            _store(), [SemanticQuery(vector=[1.0, 0.0])], top_k=3, strategy="nope"
        )


def test_semantic_search_multi_query_max_score_strategy():
    store = InMemoryVectorStore(
        [
            ("a", [1.0, 0.0]),  # strongly matches query 1 only
            ("b", [0.0, 1.0]),  # strongly matches query 2 only
        ]
    )
    hits = semantic_search(
        store,
        [SemanticQuery(vector=[1.0, 0.0]), SemanticQuery(vector=[0.0, 1.0])],
        top_k=2,
        strategy="max_score",
    )
    # Both documents get their best (=1.0) score under max_score, so they
    # tie and the deterministic tie-break (id asc) decides order.
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(1.0)


def test_semantic_search_multi_query_weighted_average_strategy():
    store = InMemoryVectorStore(
        [
            ("a", [1.0, 0.0]),
            ("b", [0.0, 1.0]),
        ]
    )
    hits = semantic_search(
        store,
        [SemanticQuery(vector=[1.0, 0.0]), SemanticQuery(vector=[0.0, 1.0])],
        top_k=2,
        strategy="weighted_average",
    )
    scores = {h.id: h.score for h in hits}
    # "a" matches query 1 perfectly (1.0) and query 2 orthogonally (0.0)
    # -> mean 0.5; symmetric for "b".
    assert scores["a"] == pytest.approx(0.5)
    assert scores["b"] == pytest.approx(0.5)


def test_semantic_search_weighted_average_lets_one_query_dominate():
    store = InMemoryVectorStore(
        [
            ("a", [1.0, 0.0]),
            ("b", [0.0, 1.0]),
        ]
    )
    hits = semantic_search(
        store,
        [
            SemanticQuery(vector=[1.0, 0.0], weight=3.0),
            SemanticQuery(vector=[0.0, 1.0], weight=1.0),
        ],
        top_k=2,
        strategy="weighted_average",
    )
    # "a" is favored by the heavily-weighted first query.
    assert hits[0].id == "a"
    assert hits[0].score > hits[1].score


def test_semantic_search_candidate_pool_size_limits_per_query_candidates():
    # "c" is a strong match for neither query's top-1 pick, so with a
    # pool size of 1 per query it never enters the combination step at
    # all, even though it might otherwise have ranked respectably.
    store = InMemoryVectorStore(
        [
            ("a", [1.0, 0.0]),
            ("b", [0.0, 1.0]),
            ("c", [0.6, 0.6]),
        ]
    )
    hits = semantic_search(
        store,
        [SemanticQuery(vector=[1.0, 0.0]), SemanticQuery(vector=[0.0, 1.0])],
        top_k=3,
        strategy="max_score",
        candidate_pool_size=1,
    )
    assert {h.id for h in hits} == {"a", "b"}


def test_semantic_search_candidate_pool_size_defaults_to_top_k():
    # With no explicit candidate_pool_size, pool size == top_k == 1, so
    # only each query's single best candidate is ever considered.
    store = InMemoryVectorStore(
        [
            ("a", [1.0, 0.0]),
            ("b", [0.0, 1.0]),
            ("c", [0.6, 0.6]),
        ]
    )
    hits = semantic_search(
        store,
        [SemanticQuery(vector=[1.0, 0.0]), SemanticQuery(vector=[0.0, 1.0])],
        top_k=1,
        strategy="max_score",
    )
    assert len(hits) == 1
    assert hits[0].id in {"a", "b"}


def test_semantic_search_is_deterministic_across_repeated_calls():
    store = _store()
    queries = [SemanticQuery(vector=[1.0, 0.0]), SemanticQuery(vector=[0.5, 0.5])]
    first = semantic_search(store, queries, top_k=3, strategy="weighted_average")
    second = semantic_search(store, queries, top_k=3, strategy="weighted_average")
    assert [h.id for h in first] == [h.id for h in second]
    assert [h.score for h in first] == [h.score for h in second]
