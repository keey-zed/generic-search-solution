"""
tests/test_fuzzy_title_filter.py

Phase 3, item 2: tests for the real reference custom filter,
`FuzzyTitleContainsFilter` (app/custom/books/fuzzy_title_filter.py).

Split into two parts:
  1. Unit tests against the filter class directly, covering its own
     behavior and construction-time validation.
  2. An integration test proving it's actually wired into the books
     project's SearchEngine and reproduces the source doc's own §4
     example verbatim: a query for "Al-Tabaqat al-Kubra" finds the
     record stored (per app/custom/books/raw_loader.py) as "Kitab
     al-Tabaqat al-Kabir" -- and proves the generic ContainsFilter,
     given the identical query, finds nothing.
"""
from __future__ import annotations

import pytest

from app.api import SearchRequest
from app.core.filtering import ContainsFilter, FilterError
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument
from app.core.search.lexical import LexicalQuery
from app.custom.books.fuzzy_title_filter import FuzzyTitleContainsFilter


def doc(id_, title):
    return NormalizedDocument(id=id_, text=f"text of {id_}", metadata={"title": title})


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


def test_construction_succeeds_for_string_field():
    FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)


def test_rejects_int_field_type():
    """INT isn't compatible with 'contains' at all -- Filter.__init__'s
    own generic compatibility check (base.py) catches this before this
    filter's own STRING-only check ever runs, which is correct: the
    generic check is strictly more general and should fire first."""
    with pytest.raises(FilterError, match="not compatible with field_type"):
        FuzzyTitleContainsFilter(field_type=MetadataFieldType.INT)


def test_rejects_list_field_type_even_though_generic_contains_allows_it():
    """'contains' IS compatible with LIST per the generic compatibility
    table (Filter.__init__ would allow it) -- this filter additionally
    restricts itself to STRING only, and must say so clearly rather than
    behaving unpredictably on a LIST field."""
    with pytest.raises(FilterError, match="only supports field_type STRING"):
        FuzzyTitleContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)


def test_rejects_threshold_at_or_below_zero():
    with pytest.raises(FilterError, match="threshold must be"):
        FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING, threshold=0.0)


def test_rejects_threshold_above_one():
    with pytest.raises(FilterError, match="threshold must be"):
        FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING, threshold=1.5)


def test_threshold_of_exactly_one_is_allowed():
    FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING, threshold=1.0)


def test_operation_matches_generic_contains():
    """Must declare the SAME operation as the generic filter it can
    override -- see config_loader.py's override-matching check."""
    assert FuzzyTitleContainsFilter.operation == "contains" == ContainsFilter.operation


# ---------------------------------------------------------------------------
# Matching behavior
# ---------------------------------------------------------------------------


def test_exact_substring_still_matches():
    """A strict superset of exact substring matching -- ratio 1.0 is
    always found by the sliding window."""
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Kitab al-Tabaqat al-Kabir")]
    result = f.apply(records, "title", "al-Tabaqat al-Kabir")
    assert [r.id for r in result] == ["d1"]


def test_transliteration_variance_still_matches():
    """The source doc's own §4 scenario: the query spells the title
    differently than the catalog does, and it should still match."""
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Kitab al-Tabaqat al-Kabir")]
    result = f.apply(records, "title", "Al-Tabaqat al-Kubra")
    assert [r.id for r in result] == ["d1"]


def test_accent_and_case_differences_still_match():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "al-Ṭabaqāt al-Kubrā")]
    result = f.apply(records, "title", "AL-TABAQAT AL-KUBRA")
    assert [r.id for r in result] == ["d1"]


def test_unrelated_query_does_not_match():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Kitab al-Tabaqat al-Kabir")]
    result = f.apply(records, "title", "Tarikh Dimashq")
    assert result == []


def test_higher_threshold_is_stricter():
    records = [doc("d1", "Kitab al-Tabaqat al-Kabir")]
    lenient = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING, threshold=0.6)
    strict = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING, threshold=0.99)

    typo_heavy_query = "al-Tabakaat al-Kabeer"
    assert [r.id for r in lenient.apply(records, "title", typo_heavy_query)] == ["d1"]
    assert strict.apply(records, "title", typo_heavy_query) == []


def test_multiple_query_values_is_or():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Kitab al-Tabaqat al-Kabir"), doc("d2", "Tarikh Dimashq")]
    result = f.apply(records, "title", ["Tabaqat", "Dimashq"])
    assert {r.id for r in result} == {"d1", "d2"}


def test_missing_field_never_matches():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", None)]
    result = f.apply(records, "title", "anything")
    assert result == []


def test_empty_params_is_noop():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Tarikh Dimashq")]
    assert [r.id for r in f.apply(records, "title", [])] == ["d1"]


def test_none_params_is_noop():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Tarikh Dimashq")]
    assert [r.id for r in f.apply(records, "title", None)] == ["d1"]


def test_does_not_mutate_input_list():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Tarikh Dimashq")]
    original = list(records)
    f.apply(records, "title", "Dimashq")
    assert records == original


def test_query_longer_than_haystack_does_not_crash():
    f = FuzzyTitleContainsFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "Al-Kitab")]
    result = f.apply(records, "title", "Kitab al-Tabaqat al-Kabir wa men ba'dahu")
    assert result == []  # too different overall, not a crash


# ---------------------------------------------------------------------------
# Integration: wired into the books SearchEngine, reproduces §4's example
# verbatim, and proves the generic filter would have found nothing.
# ---------------------------------------------------------------------------


@pytest.fixture()
def books_engine():
    from app.custom.books.bootstrap import build_search_engine

    return build_search_engine()


def test_books_title_field_uses_fuzzy_filter(books_engine):
    assert isinstance(books_engine._filters["title"], FuzzyTitleContainsFilter)


def test_books_fuzzy_title_finds_al_tabaqat_al_kubra_end_to_end(books_engine):
    """The source doc's §4 example, run for real: querying the
    commonly-known transliteration finds the record stored under a
    different transliteration."""
    request = SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"title": "Al-Tabaqat al-Kubra"},
    )
    page = books_engine.search(request)
    assert {hit.id for hit in page.hits} == {"book-1"}


def test_generic_contains_filter_would_have_found_nothing_for_same_query():
    """The comparison point: proves the override changes real behavior,
    not just which class name is selected."""
    records = [
        NormalizedDocument(
            id="book-1",
            text="...",
            metadata={"title": "Kitab al-Tabaqat al-Kabir"},
        )
    ]
    generic = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = generic.apply(records, "title", "Al-Tabaqat al-Kubra")
    assert result == []


def test_books_fuzzy_title_exact_query_still_works_end_to_end(books_engine):
    request = SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"title": "Tarikh Dimashq"},
    )
    page = books_engine.search(request)
    assert {hit.id for hit in page.hits} == {"book-2"}