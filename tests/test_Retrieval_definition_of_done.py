"""
tests/test_Retrieval_definition_of_done.py

Retrieval Definition of Done: "Given a fixed fake corpus + fake
embeddings, semantic, lexical, and combined queries return
deterministic, tested results."

Everything below uses ONE fixed corpus and ONE fixed set of embeddings,
defined once at module level, exercised by three kinds of query
(semantic-only, lexical-only, combined) with exact expected outputs
computed by hand (see the comments next to `_FIXED_EMBEDDINGS`) rather
than merely checking loose properties like "ordering looks plausible."
Vocabulary is deliberately neutral (colors/shapes) rather than drawn
from any real domain, both to keep the corpus obviously use-case-free
and to make it visually obvious this module makes no domain assumptions
-- see test_no_domain_vocabulary.py for the corresponding check against
the actual source code.
"""
from __future__ import annotations

import pytest

from app.core.search.lexical.engine import lexical_search
from app.core.search.lexical.query import LexicalQuery
from app.core.search.pagination.engine import paginate
from app.core.search.ranking.engine import merge_and_rank
from app.core.search.semantic.engine import SemanticQuery, semantic_search
from app.core.search.semantic.vector_store import InMemoryVectorStore

# ---------------------------------------------------------------------------
# The fixed fake corpus + fixed fake embeddings.
# ---------------------------------------------------------------------------

_FIXED_TEXT_CORPUS = [
    ("item-1", "red circle spinning"),
    ("item-2", "blue circle bouncing"),
    ("item-3", "red square resting"),
    ("item-4", "green triangle rolling"),
    ("item-5", "blue triangle flying"),
]

# Hand-picked 2D vectors so cosine similarity against the query vector
# [1.0, 0.0] is exact and easy to verify by hand:
#   item-1 [1.0, 0.0] is unit length, parallel to the query    -> cos = 1.0
#   item-2 [0.8, 0.6] is already unit length (0.8^2+0.6^2=1)   -> cos = 0.8
#   item-3 [0.6, 0.8] is already unit length (0.6^2+0.8^2=1)   -> cos = 0.6
#   item-4 [0.0, 1.0] is orthogonal to the query                -> cos = 0.0
#   item-5 [-1.0, 0.0] is antiparallel to the query              -> cos = -1.0
_FIXED_EMBEDDINGS = {
    "item-1": [1.0, 0.0],
    "item-2": [0.8, 0.6],
    "item-3": [0.6, 0.8],
    "item-4": [0.0, 1.0],
    "item-5": [-1.0, 0.0],
}

_QUERY_VECTOR = [1.0, 0.0]


def _fixed_vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore(list(_FIXED_EMBEDDINGS.items()))


# ---------------------------------------------------------------------------
# Semantic-only query
# ---------------------------------------------------------------------------


def test_semantic_query_returns_exact_deterministic_scores():
    hits = semantic_search(
        _fixed_vector_store(), [SemanticQuery(vector=_QUERY_VECTOR)], top_k=5
    )
    assert [(h.id, pytest.approx(h.score)) for h in hits] == [
        ("item-1", pytest.approx(1.0)),
        ("item-2", pytest.approx(0.8)),
        ("item-3", pytest.approx(0.6)),
        ("item-4", pytest.approx(0.0)),
        ("item-5", pytest.approx(-1.0)),
    ]


def test_semantic_query_is_deterministic_across_repeated_runs():
    first = semantic_search(_fixed_vector_store(), [SemanticQuery(vector=_QUERY_VECTOR)], top_k=5)
    second = semantic_search(_fixed_vector_store(), [SemanticQuery(vector=_QUERY_VECTOR)], top_k=5)
    assert [(h.id, h.score) for h in first] == [(h.id, h.score) for h in second]


# ---------------------------------------------------------------------------
# Lexical-only query
# ---------------------------------------------------------------------------


def test_lexical_first_of_returns_exact_expected_ids():
    rule = LexicalQuery(first_of=["red", "blue"])
    hits = lexical_search(_FIXED_TEXT_CORPUS, rule)
    # Matches every item except "item-4" ("green triangle rolling").
    assert [h.id for h in hits] == ["item-1", "item-2", "item-3", "item-5"]
    assert all(h.score is None for h in hits)


def test_lexical_mandatories_returns_exact_expected_ids():
    rule = LexicalQuery(mandatories=["circle"])
    hits = lexical_search(_FIXED_TEXT_CORPUS, rule)
    assert [h.id for h in hits] == ["item-1", "item-2"]


def test_lexical_grouped_mandatories_returns_exact_expected_ids():
    # (red AND circle) OR (blue AND triangle)
    rule = LexicalQuery(mandatories=[["red", "circle"], ["blue", "triangle"]])
    hits = lexical_search(_FIXED_TEXT_CORPUS, rule)
    # item-1 "red circle spinning" satisfies group 1.
    # item-5 "blue triangle flying" satisfies group 2.
    # item-3 "red square resting" has "red" but not "circle" -> excluded.
    # item-2 "blue circle bouncing" has "blue" but not "triangle" -> excluded.
    assert [h.id for h in hits] == ["item-1", "item-5"]


def test_lexical_undefined_rule_matches_every_document():
    hits = lexical_search(_FIXED_TEXT_CORPUS, LexicalQuery())
    assert [h.id for h in hits] == ["item-1", "item-2", "item-3", "item-4", "item-5"]


def test_lexical_query_is_deterministic_across_repeated_runs():
    rule = LexicalQuery(first_of=["red", "blue"])
    first = lexical_search(_FIXED_TEXT_CORPUS, rule)
    second = lexical_search(_FIXED_TEXT_CORPUS, rule)
    assert [h.id for h in first] == [h.id for h in second]


# ---------------------------------------------------------------------------
# Combined query: semantic + lexical -> merge_and_rank -> paginate
# ---------------------------------------------------------------------------


def _combined_ranked_hits():
    semantic_hits = semantic_search(
        _fixed_vector_store(), [SemanticQuery(vector=_QUERY_VECTOR)], top_k=5
    )
    lexical_hits = lexical_search(_FIXED_TEXT_CORPUS, LexicalQuery(first_of=["red", "blue"]))
    return merge_and_rank(semantic_hits, lexical_hits)


def test_combined_query_returns_exact_expected_ranking():
    # weighted_sum, default weights {semantic: 0.5, lexical: 0.5}:
    #   item-1: 0.5*1.0 + 0.5*1 (lexical hit)  = 1.0
    #   item-2: 0.5*0.8 + 0.5*1 (lexical hit)  = 0.9
    #   item-3: 0.5*0.6 + 0.5*1 (lexical hit)  = 0.8
    #   item-4: 0.5*0.0 + 0.5*0 (no lexical)   = 0.0
    #   item-5: 0.5*(-1.0) + 0.5*1 (lexical hit) = 0.0
    # item-4 and item-5 tie at 0.0; tie-break by id ascending puts
    # "item-4" before "item-5".
    hits = _combined_ranked_hits()
    assert [(h.id, pytest.approx(h.score)) for h in hits] == [
        ("item-1", pytest.approx(1.0)),
        ("item-2", pytest.approx(0.9)),
        ("item-3", pytest.approx(0.8)),
        ("item-4", pytest.approx(0.0)),
        ("item-5", pytest.approx(0.0)),
    ]


def test_combined_query_paginates_deterministically():
    ranked = _combined_ranked_hits()

    page_1 = paginate(ranked, page=1, page_size=2)
    assert [h.id for h in page_1.hits] == ["item-1", "item-2"]
    assert page_1.total_hits == 5
    assert page_1.total_pages == 3
    assert page_1.has_previous is False
    assert page_1.has_next is True

    page_3 = paginate(ranked, page=3, page_size=2)
    assert [h.id for h in page_3.hits] == ["item-5"]
    assert page_3.has_previous is True
    assert page_3.has_next is False


def test_combined_query_is_deterministic_across_repeated_runs():
    first = _combined_ranked_hits()
    second = _combined_ranked_hits()
    assert [(h.id, h.score) for h in first] == [(h.id, h.score) for h in second]
