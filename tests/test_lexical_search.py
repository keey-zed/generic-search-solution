import pytest
from pydantic import ValidationError

from app.core.schema.search_hit import SearchHit
from app.core.search.lexical.boolean_expr import And, MatchAll, Or, Term
from app.core.search.lexical.engine import contains_predicate, lexical_search
from app.core.search.lexical.query import (
    LexicalQuery,
    build_first_of_expr,
    build_mandatories_expr,
)


# ---------------------------------------------------------------------------
# BooleanExpr tree: Term / And / Or / MatchAll
# ---------------------------------------------------------------------------


def _predicate(true_terms):
    """A trivial TermPredicate: term matches iff it's in `true_terms`."""
    true_set = set(true_terms)
    return lambda term: term in true_set


def test_term_rejects_blank():
    with pytest.raises(ValidationError):
        Term(term="   ")


def test_term_evaluates_via_predicate():
    assert Term(term="a").evaluate(_predicate(["a"])) is True
    assert Term(term="a").evaluate(_predicate(["b"])) is False


def test_and_requires_all_children_true():
    expr = And(children=[Term(term="a"), Term(term="b")])
    assert expr.evaluate(_predicate(["a", "b"])) is True
    assert expr.evaluate(_predicate(["a"])) is False
    assert expr.evaluate(_predicate([])) is False


def test_and_rejects_empty_children():
    with pytest.raises(ValidationError):
        And(children=[])


def test_or_requires_any_child_true():
    expr = Or(children=[Term(term="a"), Term(term="b")])
    assert expr.evaluate(_predicate(["a"])) is True
    assert expr.evaluate(_predicate(["b"])) is True
    assert expr.evaluate(_predicate([])) is False


def test_or_rejects_empty_children():
    with pytest.raises(ValidationError):
        Or(children=[])


def test_match_all_always_true():
    assert MatchAll().evaluate(_predicate([])) is True
    assert MatchAll().evaluate(lambda term: False) is True


def test_nested_expression_or_of_ands():
    # (a AND b) OR (c AND d)
    expr = Or(
        children=[
            And(children=[Term(term="a"), Term(term="b")]),
            And(children=[Term(term="c"), Term(term="d")]),
        ]
    )
    assert expr.evaluate(_predicate(["a", "b"])) is True
    assert expr.evaluate(_predicate(["c", "d"])) is True
    assert expr.evaluate(_predicate(["a", "d"])) is False
    assert expr.evaluate(_predicate([])) is False


def test_deeper_nesting_works_with_no_special_casing():
    # ((a AND b) OR c) AND d  -- three levels deep, no dedicated node type
    inner = Or(children=[And(children=[Term(term="a"), Term(term="b")]), Term(term="c")])
    expr = And(children=[inner, Term(term="d")])
    assert expr.evaluate(_predicate(["a", "b", "d"])) is True
    assert expr.evaluate(_predicate(["c", "d"])) is True
    assert expr.evaluate(_predicate(["c"])) is False  # missing d
    assert expr.evaluate(_predicate(["d"])) is False  # neither a+b nor c


# ---------------------------------------------------------------------------
# build_first_of_expr (OR)
# ---------------------------------------------------------------------------


def test_build_first_of_expr_is_or_of_terms():
    expr = build_first_of_expr(["a", "b", "c"])
    assert isinstance(expr, Or)
    assert expr.evaluate(_predicate(["b"])) is True
    assert expr.evaluate(_predicate(["z"])) is False


def test_build_first_of_expr_rejects_empty_list():
    with pytest.raises(ValueError):
        build_first_of_expr([])


# ---------------------------------------------------------------------------
# build_mandatories_expr (AND, and grouped AND/OR)
# ---------------------------------------------------------------------------


def test_build_mandatories_expr_flat_is_and_of_terms():
    expr = build_mandatories_expr(["a", "b", "c"])
    assert isinstance(expr, And)
    assert expr.evaluate(_predicate(["a", "b", "c"])) is True
    assert expr.evaluate(_predicate(["a", "b"])) is False


def test_build_mandatories_expr_grouped_is_or_of_ands():
    expr = build_mandatories_expr([["a1", "a2", "a3"], ["b1", "b2", "b3"]])
    assert isinstance(expr, Or)
    assert expr.evaluate(_predicate(["a1", "a2", "a3"])) is True
    assert expr.evaluate(_predicate(["b1", "b2", "b3"])) is True
    assert expr.evaluate(_predicate(["a1", "a2", "b1"])) is False  # neither group fully satisfied
    assert expr.evaluate(_predicate([])) is False


def test_build_mandatories_expr_single_group_still_wrapped_in_or():
    expr = build_mandatories_expr([["a1", "a2"]])
    assert isinstance(expr, Or)
    assert expr.evaluate(_predicate(["a1", "a2"])) is True
    assert expr.evaluate(_predicate(["a1"])) is False


def test_build_mandatories_expr_rejects_empty_list():
    with pytest.raises(ValueError):
        build_mandatories_expr([])


def test_build_mandatories_expr_rejects_empty_group():
    with pytest.raises(ValueError):
        build_mandatories_expr([["a1"], []])


def test_build_mandatories_expr_rejects_mixed_bare_terms_and_groups():
    with pytest.raises(ValueError):
        build_mandatories_expr(["a", ["b", "c"]])


# ---------------------------------------------------------------------------
# LexicalQuery
# ---------------------------------------------------------------------------


def test_lexical_query_rejects_blank_first_of_term():
    with pytest.raises(ValidationError):
        LexicalQuery(first_of=["a", "   "])


def test_lexical_query_rejects_blank_mandatories_term_flat():
    with pytest.raises(ValidationError):
        LexicalQuery(mandatories=["a", ""])


def test_lexical_query_rejects_blank_mandatories_term_grouped():
    with pytest.raises(ValidationError):
        LexicalQuery(mandatories=[["a", "b"], ["c", "   "]])


def test_lexical_query_rejects_mixed_mandatories_shape():
    with pytest.raises(ValidationError):
        LexicalQuery(mandatories=["a", ["b", "c"]])


def test_lexical_query_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        LexicalQuery(first_of=["a"], boost=2.0)


def test_lexical_query_to_boolean_expr_single_or():
    expr = LexicalQuery(first_of=["a", "b"]).to_boolean_expr()
    assert isinstance(expr, Or)


def test_lexical_query_to_boolean_expr_single_and():
    expr = LexicalQuery(mandatories=["a", "b"]).to_boolean_expr()
    assert isinstance(expr, And)


def test_lexical_query_to_boolean_expr_grouped():
    expr = LexicalQuery(mandatories=[["a", "b"], ["c", "d"]]).to_boolean_expr()
    assert isinstance(expr, Or)
    assert all(isinstance(child, And) for child in expr.children)


def test_lexical_query_to_boolean_expr_empty_fields_default_to_match_all():
    expr = LexicalQuery(first_of=[], mandatories=[]).to_boolean_expr()
    assert isinstance(expr, MatchAll)


def test_lexical_query_to_boolean_expr_undefined_fields_default_to_match_all():
    expr = LexicalQuery().to_boolean_expr()
    assert isinstance(expr, MatchAll)
    assert expr.evaluate(lambda term: False) is True


def test_lexical_query_to_boolean_expr_combines_first_of_and_mandatories_with_and():
    expr = LexicalQuery(first_of=["a", "b"], mandatories=["c"]).to_boolean_expr()
    assert isinstance(expr, And)
    # Must satisfy the mandatory "c" AND at least one of first_of ("a" or "b").
    assert expr.evaluate(_predicate(["a", "c"])) is True
    assert expr.evaluate(_predicate(["a"])) is False  # missing mandatory "c"
    assert expr.evaluate(_predicate(["c"])) is False  # missing any first_of term


# ---------------------------------------------------------------------------
# contains_predicate
# ---------------------------------------------------------------------------


def test_contains_predicate_case_insensitive_by_default():
    predicate = contains_predicate("The Quick Brown Fox")
    assert predicate("quick") is True
    assert predicate("QUICK") is True
    assert predicate("slow") is False


def test_contains_predicate_case_sensitive_when_requested():
    predicate = contains_predicate("The Quick Brown Fox", case_sensitive=True)
    assert predicate("Quick") is True
    assert predicate("quick") is False


# ---------------------------------------------------------------------------
# lexical_search (end to end)
# ---------------------------------------------------------------------------


def _corpus():
    return [
        ("doc-1", "public procurement rules for construction"),
        ("doc-2", "taxation policy for small businesses"),
        ("doc-3", "public taxation reform announced"),
        ("doc-4", "unrelated document about weather"),
    ]


def test_lexical_search_first_of_matches_any():
    rule = LexicalQuery(first_of=["procurement", "weather"])
    hits = lexical_search(_corpus(), rule)
    assert [h.id for h in hits] == ["doc-1", "doc-4"]


def test_lexical_search_mandatories_matches_all():
    rule = LexicalQuery(mandatories=["public", "taxation"])
    hits = lexical_search(_corpus(), rule)
    assert [h.id for h in hits] == ["doc-3"]


def test_lexical_search_grouped_mandatories():
    rule = LexicalQuery(
        mandatories=[["public", "procurement"], ["taxation", "reform"]]
    )
    hits = lexical_search(_corpus(), rule)
    assert [h.id for h in hits] == ["doc-1", "doc-3"]


def test_lexical_search_empty_rule_matches_all_documents():
    rule = LexicalQuery()
    hits = lexical_search(_corpus(), rule)
    assert [h.id for h in hits] == ["doc-1", "doc-2", "doc-3", "doc-4"]


def test_lexical_search_no_matches_returns_empty_list():
    rule = LexicalQuery(first_of=["nonexistent-term"])
    hits = lexical_search(_corpus(), rule)
    assert hits == []


def test_lexical_search_hits_have_no_score():
    rule = LexicalQuery(first_of=["procurement"])
    hits = lexical_search(_corpus(), rule)
    assert all(isinstance(h, SearchHit) for h in hits)
    assert all(h.score is None for h in hits)


def test_lexical_search_matched_fields_defaults_to_text():
    rule = LexicalQuery(first_of=["procurement"])
    hits = lexical_search(_corpus(), rule)
    assert hits[0].matched_fields == ["text"]


def test_lexical_search_results_sorted_by_id_regardless_of_input_order():
    reversed_corpus = list(reversed(_corpus()))
    rule = LexicalQuery()
    hits = lexical_search(reversed_corpus, rule)
    assert [h.id for h in hits] == ["doc-1", "doc-2", "doc-3", "doc-4"]


def test_lexical_search_case_sensitivity_is_configurable():
    corpus = [("doc-1", "Public Procurement")]
    rule = LexicalQuery(first_of=["public"])
    assert lexical_search(corpus, rule, case_sensitive=False) != []
    assert lexical_search(corpus, rule, case_sensitive=True) == []
