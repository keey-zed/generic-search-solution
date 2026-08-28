import pytest

from app.core.filtering.base import Filter, FilterError
from app.core.filtering.filters import ContainsFilter, EqualityFilter, RangeFilter
from app.core.filtering.registry import get_filter_class, list_registered_operations, register_filter
from app.core.schema.metadata_types import MetadataFieldType


def test_builtin_filters_are_registered():
    ops = list_registered_operations()
    assert "equality" in ops
    assert "range" in ops
    assert "contains" in ops


def test_get_filter_class_returns_expected_class():
    assert get_filter_class("equality") is EqualityFilter
    assert get_filter_class("range") is RangeFilter
    assert get_filter_class("contains") is ContainsFilter


def test_get_filter_class_unknown_operation_raises_clear_error():
    with pytest.raises(FilterError, match="no filter is registered"):
        get_filter_class("fuzzy_match")


def test_register_filter_rejects_mismatched_operation_attribute():
    with pytest.raises(ValueError, match="must match"):

        @register_filter("something_else")
        class BadFilter(Filter):
            operation = "not_something_else"

            def apply(self, records, field, params):
                return list(records)


def test_register_filter_rejects_duplicate_operation_name():
    with pytest.raises(ValueError, match="already registered"):

        @register_filter("equality")
        class DuplicateEqualityFilter(Filter):
            operation = "equality"

            def apply(self, records, field, params):
                return list(records)


def test_reregistering_same_class_under_same_operation_is_allowed():
    """Re-decorating the exact same class object (e.g. module reimport)
    must not be treated as a conflicting duplicate."""
    register_filter("equality")(EqualityFilter)  # should not raise
    assert get_filter_class("equality") is EqualityFilter


# ---------------------------------------------------------------------------
# Filter.__init__ compatibility checks (defense in depth vs task 3's loader)
# ---------------------------------------------------------------------------


def test_filter_rejects_incompatible_operation_for_type():
    with pytest.raises(FilterError, match="not compatible"):
        ContainsFilter(field_type=MetadataFieldType.BOOL)


def test_filter_rejects_range_on_string():
    with pytest.raises(FilterError, match="not compatible"):
        RangeFilter(field_type=MetadataFieldType.STRING)


def test_filter_rejects_contains_on_int():
    with pytest.raises(FilterError, match="not compatible"):
        ContainsFilter(field_type=MetadataFieldType.INT)


def test_filter_list_type_requires_item_type():
    with pytest.raises(FilterError, match="item_type is required"):
        ContainsFilter(field_type=MetadataFieldType.LIST)


def test_filter_non_list_type_rejects_item_type():
    with pytest.raises(FilterError, match="item_type must only be set"):
        EqualityFilter(field_type=MetadataFieldType.STRING, item_type=MetadataFieldType.STRING)


def test_filter_valid_construction_succeeds():
    EqualityFilter(field_type=MetadataFieldType.STRING)
    RangeFilter(field_type=MetadataFieldType.DATE)
    RangeFilter(field_type=MetadataFieldType.INT)
    RangeFilter(field_type=MetadataFieldType.FLOAT)
    ContainsFilter(field_type=MetadataFieldType.STRING)
    ContainsFilter(field_type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    EqualityFilter(field_type=MetadataFieldType.BOOL)