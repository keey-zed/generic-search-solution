from datetime import date

import pytest

from app.core.filtering.base import FilterError
from app.core.filtering.filters import ContainsFilter, EqualityFilter, RangeFilter
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument


def doc(id_, **metadata):
    return NormalizedDocument(id=id_, text=f"text of {id_}", metadata=metadata)


# ---------------------------------------------------------------------------
# EqualityFilter
# ---------------------------------------------------------------------------


def test_equality_string_single_value():
    records = [doc("d1", doctype="dahir"), doc("d2", doctype="marsoum")]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", "dahir")
    assert [r.id for r in result] == ["d1"]


def test_equality_string_multiple_values_is_or():
    records = [doc("d1", doctype="dahir"), doc("d2", doctype="marsoum"), doc("d3", doctype="9anoun")]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", ["dahir", "marsoum"])
    assert {r.id for r in result} == {"d1", "d2"}


def test_equality_bool():
    records = [doc("d1", is_amended=True), doc("d2", is_amended=False)]
    f = EqualityFilter(field_type=MetadataFieldType.BOOL)
    result = f.apply(records, "is_amended", True)
    assert [r.id for r in result] == ["d1"]


def test_equality_int():
    records = [doc("d1", page_count=10), doc("d2", page_count=20)]
    f = EqualityFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "page_count", 20)
    assert [r.id for r in result] == ["d2"]


def test_equality_float():
    records = [doc("d1", score=0.5), doc("d2", score=0.9)]
    f = EqualityFilter(field_type=MetadataFieldType.FLOAT)
    result = f.apply(records, "score", 0.9)
    assert [r.id for r in result] == ["d2"]


def test_equality_date_string_param_coerced():
    records = [doc("d1", pub_date=date(2020, 1, 1)), doc("d2", pub_date=date(2021, 1, 1))]
    f = EqualityFilter(field_type=MetadataFieldType.DATE)
    result = f.apply(records, "pub_date", "2020-01-01")
    assert [r.id for r in result] == ["d1"]


def test_equality_empty_params_is_noop():
    records = [doc("d1", doctype="dahir"), doc("d2", doctype="marsoum")]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", [])
    assert {r.id for r in result} == {"d1", "d2"}


def test_equality_none_params_is_noop():
    records = [doc("d1", doctype="dahir")]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", None)
    assert [r.id for r in result] == ["d1"]


def test_equality_missing_field_never_matches():
    records = [doc("d1", doctype="dahir"), doc("d2")]  # d2 has no doctype key at all
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", "dahir")
    assert [r.id for r in result] == ["d1"]


def test_equality_none_field_value_never_matches():
    records = [doc("d1", doctype="dahir"), doc("d2", doctype=None)]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "doctype", "dahir")
    assert [r.id for r in result] == ["d1"]


def test_equality_wrong_type_param_raises():
    records = [doc("d1", doctype="dahir")]
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    with pytest.raises(FilterError):
        f.apply(records, "doctype", 123)


def test_equality_bool_int_trap_rejected():
    """isinstance(True, int) is True in Python -- this must not let a
    bool silently pass as an int equality param."""
    records = [doc("d1", page_count=1)]
    f = EqualityFilter(field_type=MetadataFieldType.INT)
    with pytest.raises(FilterError):
        f.apply(records, "page_count", True)


# ---------------------------------------------------------------------------
# RangeFilter
# ---------------------------------------------------------------------------


def test_range_date_inclusive_both_bounds():
    records = [doc("d1", pub_date=date(2020, 1, 1)), doc("d2", pub_date=date(2020, 6, 1)), doc("d3", pub_date=date(2021, 1, 1))]
    f = RangeFilter(field_type=MetadataFieldType.DATE)
    result = f.apply(records, "pub_date", {"min": "2020-01-01", "max": "2020-12-31"})
    assert {r.id for r in result} == {"d1", "d2"}


def test_range_boundary_inclusive_by_default():
    records = [doc("d1", n=10), doc("d2", n=20)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"min": 10, "max": 20})
    assert {r.id for r in result} == {"d1", "d2"}


def test_range_min_exclusive():
    records = [doc("d1", n=10), doc("d2", n=11)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"min": 10, "min_inclusive": False})
    assert {r.id for r in result} == {"d2"}


def test_range_max_exclusive():
    records = [doc("d1", n=20), doc("d2", n=19)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"max": 20, "max_inclusive": False})
    assert {r.id for r in result} == {"d2"}


def test_range_only_min_bound():
    records = [doc("d1", n=5), doc("d2", n=15)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"min": 10})
    assert {r.id for r in result} == {"d2"}


def test_range_only_max_bound():
    records = [doc("d1", n=5), doc("d2", n=15)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"max": 10})
    assert {r.id for r in result} == {"d1"}


def test_range_float():
    records = [doc("d1", score=0.4), doc("d2", score=0.6)]
    f = RangeFilter(field_type=MetadataFieldType.FLOAT)
    result = f.apply(records, "score", {"min": 0.5})
    assert {r.id for r in result} == {"d2"}


def test_range_empty_params_is_noop():
    records = [doc("d1", n=5), doc("d2", n=15)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {})
    assert {r.id for r in result} == {"d1", "d2"}


def test_range_none_params_is_noop():
    records = [doc("d1", n=5)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", None)
    assert [r.id for r in result] == ["d1"]


def test_range_both_bounds_none_is_noop():
    records = [doc("d1", n=5)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"min": None, "max": None})
    assert [r.id for r in result] == ["d1"]


def test_range_missing_field_never_matches():
    records = [doc("d1", n=5), doc("d2")]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    result = f.apply(records, "n", {"min": 0, "max": 10})
    assert [r.id for r in result] == ["d1"]


def test_range_min_greater_than_max_raises():
    records = [doc("d1", n=5)]
    f = RangeFilter(field_type=MetadataFieldType.INT)
    with pytest.raises(FilterError, match="greater"):
        f.apply(records, "n", {"min": 10, "max": 5})


def test_range_wrong_type_bound_raises():
    records = [doc("d1", pub_date=date(2020, 1, 1))]
    f = RangeFilter(field_type=MetadataFieldType.DATE)
    with pytest.raises(FilterError):
        f.apply(records, "pub_date", {"min": "not-a-date"})


def test_range_malformed_date_format_raises():
    records = [doc("d1", pub_date=date(2020, 1, 1))]
    f = RangeFilter(field_type=MetadataFieldType.DATE)
    with pytest.raises(FilterError):
        f.apply(records, "pub_date", {"min": "01/01/2020"})


# ---------------------------------------------------------------------------
# ContainsFilter — STRING (substring)
# ---------------------------------------------------------------------------


def test_contains_string_substring_match():
    records = [doc("d1", title="Climate Change Act"), doc("d2", title="Finance Bill")]
    f = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "title", "climate")
    assert [r.id for r in result] == ["d1"]


def test_contains_string_case_insensitive_by_default():
    records = [doc("d1", title="Climate Change Act")]
    f = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "title", "CLIMATE")
    assert [r.id for r in result] == ["d1"]


def test_contains_string_multiple_values_is_or():
    records = [doc("d1", title="Climate Change Act"), doc("d2", title="Finance Bill"), doc("d3", title="Health Code")]
    f = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "title", ["climate", "finance"])
    assert {r.id for r in result} == {"d1", "d2"}


def test_contains_string_missing_field_never_matches():
    records = [doc("d1", title="Climate Change Act"), doc("d2")]
    f = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "title", "climate")
    assert [r.id for r in result] == ["d1"]


def test_contains_string_empty_params_is_noop():
    records = [doc("d1", title="Climate Change Act")]
    f = ContainsFilter(field_type=MetadataFieldType.STRING)
    result = f.apply(records, "title", [])
    assert [r.id for r in result] == ["d1"]


# ---------------------------------------------------------------------------
# ContainsFilter — LIST (membership)
# ---------------------------------------------------------------------------


def test_contains_list_membership_single_value():
    records = [doc("d1", subjects=["finance", "tax"]), doc("d2", subjects=["health"])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", "finance")
    assert [r.id for r in result] == ["d1"]


def test_contains_list_membership_multiple_values_is_or():
    records = [doc("d1", subjects=["finance"]), doc("d2", subjects=["health"]), doc("d3", subjects=["education"])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", ["finance", "health"])
    assert {r.id for r in result} == {"d1", "d2"}


def test_contains_list_case_insensitive_for_string_items():
    records = [doc("d1", subjects=["Finance"])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", "finance")
    assert [r.id for r in result] == ["d1"]


def test_contains_list_exact_match_for_non_string_items():
    records = [doc("d1", years=[2020, 2021]), doc("d2", years=[2019])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.INT)
    result = f.apply(records, "years", 2020)
    assert [r.id for r in result] == ["d1"]


def test_contains_list_missing_field_never_matches():
    records = [doc("d1", subjects=["finance"]), doc("d2")]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", "finance")
    assert [r.id for r in result] == ["d1"]


def test_contains_list_empty_field_value_never_matches():
    records = [doc("d1", subjects=["finance"]), doc("d2", subjects=[])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", "finance")
    assert [r.id for r in result] == ["d1"]


def test_contains_list_empty_params_is_noop():
    records = [doc("d1", subjects=["finance"])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    result = f.apply(records, "subjects", [])
    assert [r.id for r in result] == ["d1"]


def test_contains_list_wrong_type_param_raises():
    records = [doc("d1", years=[2020])]
    f = ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.INT)
    with pytest.raises(FilterError):
        f.apply(records, "years", "not-an-int")


# ---------------------------------------------------------------------------
# Records not mutated
# ---------------------------------------------------------------------------


def test_apply_does_not_mutate_input_list():
    records = [doc("d1", doctype="dahir"), doc("d2", doctype="marsoum")]
    original = list(records)
    f = EqualityFilter(field_type=MetadataFieldType.STRING)
    f.apply(records, "doctype", "dahir")
    assert records == original