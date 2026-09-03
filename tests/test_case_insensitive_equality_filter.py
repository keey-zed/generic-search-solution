"""
tests/test_case_insensitive_equality_filter.py

Phase 3's overall Definition of Done: "a new filter can be added by a
third developer, following only the template and doc, without reading
core source code, and it passes a test."

This file, together with
`app/custom/legal/case_insensitive_equality_filter.py`, IS that proof:

  - The filter (see its own module docstring) was written using only
    `app/custom/_template/README.md` and `docs/custom-vs-generic.md` as
    guidance -- the imports it needs (`Filter`, `FilterError`,
    `MetadataFieldType`, `NormalizedDocument`) are exactly what the
    template's own `custom_filters.py` comments already show, without
    needing to open `app/core/filtering/filters.py`, `base.py`, or
    `config_loader.py`.
  - It follows `docs/custom-vs-generic.md`'s decision procedure (step 2:
    one project, one field, generic filter genuinely insufficient) for
    *why* it belongs in the custom layer rather than being promoted.
  - This test file proves it actually works, end to end, wired through
    the real legal `SearchEngine` -- not just "a class was written," but
    "the pattern produces correct, different-from-generic search
    results."
"""
from __future__ import annotations

import pytest

from app.api import SearchRequest
from app.core.filtering import EqualityFilter
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument
from app.core.search.lexical import LexicalQuery
from app.custom.legal.case_insensitive_equality_filter import CaseInsensitiveEqualityFilter


def doc(id_, document_type):
    return NormalizedDocument(id=id_, text=f"text of {id_}", metadata={"document_type": document_type})


# ---------------------------------------------------------------------------
# Unit tests against the filter directly
# ---------------------------------------------------------------------------


def test_operation_matches_generic_equality():
    assert CaseInsensitiveEqualityFilter.operation == "equality" == EqualityFilter.operation


def test_case_insensitive_match():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir"), doc("d2", "marsoum")]
    result = f.apply(records, "document_type", "DAHIR")
    assert [r.id for r in result] == ["d1"]


def test_multiple_values_is_or():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir"), doc("d2", "marsoum"), doc("d3", "9anoun")]
    result = f.apply(records, "document_type", ["Dahir", "MARSOUM"])
    assert {r.id for r in result} == {"d1", "d2"}


def test_unrelated_value_does_not_match():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir")]
    result = f.apply(records, "document_type", "marsoum")
    assert result == []


def test_missing_field_never_matches():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", None)]
    result = f.apply(records, "document_type", "dahir")
    assert result == []


def test_empty_params_is_noop():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir")]
    assert [r.id for r in f.apply(records, "document_type", [])] == ["d1"]


def test_none_params_is_noop():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir")]
    assert [r.id for r in f.apply(records, "document_type", None)] == ["d1"]


def test_does_not_mutate_input_list():
    f = CaseInsensitiveEqualityFilter(field_type=MetadataFieldType.STRING)
    records = [doc("d1", "dahir")]
    original = list(records)
    f.apply(records, "document_type", "DAHIR")
    assert records == original


def test_generic_equality_filter_would_have_found_nothing_for_same_query():
    """The comparison point: proves the override changes real behavior,
    not just which class name is selected."""
    records = [doc("d1", "dahir")]
    generic = EqualityFilter(field_type=MetadataFieldType.STRING)
    assert generic.apply(records, "document_type", "DAHIR") == []


# ---------------------------------------------------------------------------
# Integration: wired into the real legal SearchEngine
# ---------------------------------------------------------------------------


@pytest.fixture()
def legal_engine():
    from app.custom.legal.bootstrap import build_search_engine

    return build_search_engine()


def test_legal_document_type_field_uses_case_insensitive_filter(legal_engine):
    assert isinstance(legal_engine._filters["document_type"], CaseInsensitiveEqualityFilter)


def test_legal_mixed_case_query_finds_records_end_to_end(legal_engine):
    request = SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"document_type": "DAHIR"},  # sample data stores it lowercase
    )
    page = legal_engine.search(request)
    assert {hit.id for hit in page.hits} == {"legal-1", "legal-4"}


def test_legal_exact_case_query_still_works_end_to_end(legal_engine):
    request = SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"document_type": "dahir"},
    )
    page = legal_engine.search(request)
    assert {hit.id for hit in page.hits} == {"legal-1", "legal-4"}