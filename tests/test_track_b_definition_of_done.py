"""
tests/test_track_b_definition_of_done.py

Track B's stated Definition of Done:

    "given a fake YAML config and a fake set of normalized records,
    every filter type produces correct results on hand-written test
    cases, including edge cases (missing field, wrong type, empty
    filter list, malformed config rejected with a clear message)."

The other test files (test_ingestion.py, test_filters.py,
test_filtering_registry.py, test_filter_config_loader.py) already cover
each piece in isolation, in much more depth than this file does. This
file exists as ONE place that runs the whole Track B pipeline together,
end to end, exactly as the DoD describes it:

    fake config.yaml
         |
         v
    load_filters()               (task 3)  -> UseCaseConfig, dict[field, Filter]
         |
    fake raw records (dicts)
         |
         v
    ingest_raw_records()         (task 1)  -> IngestionReport
         |
         v
    valid, typed IngestedDocuments
         |
         v
    filters[field].apply(...)    (task 2 + task 4 registry)  -> correct results

The fake domain here ("gadgets") is deliberately NOT the legal or books
examples used elsewhere in the test suite/docs, specifically to
demonstrate genericity: nothing in ingestion or filtering knows or cares
what "category"/"tags"/"rating" mean.
"""
from datetime import date

import pytest

from app.core.config.loader import ConfigLoadError
from app.core.filtering import load_filters
from app.core.ingestion import ingest_raw_records

# ---------------------------------------------------------------------------
# The fake config: one field per operation this deliverable supports,
# covering string/date/float/bool/list and equality/range/contains.
# ---------------------------------------------------------------------------

_GADGETS_CONFIG_YAML = """
schema_version: 1
filters:
  category:
    type: string
    required: true
    operation: equality
  release_date:
    type: date
    operation: range
  rating:
    type: float
    operation: range
  in_stock:
    type: bool
    operation: equality
  tags:
    type: list
    item_type: string
    operation: contains
search: {}
frontend:
  branding:
    title: "Gadgets"
"""

# A config with an operation that doesn't exist for its field's type --
# 'contains' is not valid for 'bool' (only string/list support 'contains').
_MALFORMED_CONFIG_YAML = """
schema_version: 1
filters:
  in_stock:
    type: bool
    operation: contains
search: {}
frontend:
  branding:
    title: "Gadgets"
"""

# ---------------------------------------------------------------------------
# The fake records: a mix of clean records and every edge case the DoD
# calls out by name.
# ---------------------------------------------------------------------------

_RAW_RECORDS = [
    {
        "id": "gadget-1",
        "text": "A sturdy wireless mouse.",
        "metadata": {
            "category": "peripherals",
            "release_date": "2023-03-01",
            "rating": 4.5,
            "in_stock": True,
            "tags": ["wireless", "office"],
        },
    },
    {
        "id": "gadget-2",
        "text": "A mechanical keyboard.",
        "metadata": {
            "category": "peripherals",
            "release_date": "2022-11-15",
            "rating": 4.8,
            "in_stock": False,
            "tags": ["mechanical", "office"],
        },
    },
    {
        "id": "gadget-3",
        "text": "A gaming monitor with no tags recorded yet.",
        "metadata": {
            "category": "displays",
            "release_date": "2024-01-10",
            "rating": 4.2,
            "in_stock": True,
            # "tags" deliberately omitted -> DoD edge case: missing field.
        },
    },
    {
        "id": "gadget-4",
        "text": "A record with a metadata value of the wrong type.",
        "metadata": {
            "category": "displays",
            "release_date": "2023-07-01",
            "rating": "excellent",  # DoD edge case: wrong type (should be float)
            "in_stock": True,
            "tags": ["gaming"],
        },
    },
]


@pytest.fixture()
def gadgets_config_and_filters(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_GADGETS_CONFIG_YAML)
    return load_filters(config_path)


@pytest.fixture()
def ingested_gadgets(gadgets_config_and_filters):
    config, _filters = gadgets_config_and_filters
    schema = config.to_metadata_schema()
    return ingest_raw_records(_RAW_RECORDS, schema)


# ---------------------------------------------------------------------------
# Ingestion: the wrong-type record is rejected, everything else is typed
# ---------------------------------------------------------------------------


def test_wrong_type_record_excluded_with_clear_error(ingested_gadgets):
    ids = {d.id for d in ingested_gadgets.valid_documents}
    assert ids == {"gadget-1", "gadget-2", "gadget-3"}
    assert "gadget-4" not in ids

    error = next(e for e in ingested_gadgets.record_errors if e.record_id == "gadget-4")
    assert error.stage == "metadata_typing"
    assert any("rating" in fe.field for fe in error.errors)


def test_metadata_typed_correctly_after_ingestion(ingested_gadgets):
    gadget_1 = next(d for d in ingested_gadgets.valid_documents if d.id == "gadget-1")
    assert gadget_1.metadata["release_date"] == date(2023, 3, 1)
    assert gadget_1.metadata["rating"] == 4.5
    assert gadget_1.metadata["in_stock"] is True
    assert gadget_1.metadata["tags"] == ["wireless", "office"]


def test_missing_optional_field_is_none_after_ingestion(ingested_gadgets):
    gadget_3 = next(d for d in ingested_gadgets.valid_documents if d.id == "gadget-3")
    assert gadget_3.metadata["tags"] is None


# ---------------------------------------------------------------------------
# EqualityFilter (string, bool) — correct results + empty filter list
# ---------------------------------------------------------------------------


def test_equality_filter_string(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["category"].apply(records, "category", "peripherals")
    assert {r.id for r in result} == {"gadget-1", "gadget-2"}


def test_equality_filter_bool(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["in_stock"].apply(records, "in_stock", False)
    assert {r.id for r in result} == {"gadget-2"}


def test_equality_filter_empty_params_is_noop(gadgets_config_and_filters, ingested_gadgets):
    """DoD edge case: empty filter list -> no restriction, not zero results."""
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["category"].apply(records, "category", [])
    assert {r.id for r in result} == {r.id for r in records}


def test_equality_filter_wrong_type_param_raises_clear_error(gadgets_config_and_filters, ingested_gadgets):
    """DoD edge case: wrong type. A bool field given a non-bool filter
    value must raise, not silently match/not-match."""
    from app.core.filtering import FilterError

    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    with pytest.raises(FilterError, match="invalid filter parameter"):
        filters["in_stock"].apply(records, "in_stock", "yes")


# ---------------------------------------------------------------------------
# RangeFilter (date, float) — correct results + boundaries + missing field
# ---------------------------------------------------------------------------


def test_range_filter_date(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["release_date"].apply(
        records, "release_date", {"min": "2023-01-01", "max": "2023-12-31"}
    )
    assert {r.id for r in result} == {"gadget-1"}


def test_range_filter_float_inclusive_boundary(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["rating"].apply(records, "rating", {"min": 4.5})
    assert {r.id for r in result} == {"gadget-1", "gadget-2"}


def test_range_filter_empty_params_is_noop(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["rating"].apply(records, "rating", {})
    assert {r.id for r in result} == {r.id for r in records}


# ---------------------------------------------------------------------------
# ContainsFilter (list membership) — correct results + missing field
# ---------------------------------------------------------------------------


def test_contains_filter_list_membership(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["tags"].apply(records, "tags", "office")
    assert {r.id for r in result} == {"gadget-1", "gadget-2"}


def test_contains_filter_missing_field_never_matches(gadgets_config_and_filters, ingested_gadgets):
    """DoD edge case: missing field. gadget-3 has no `tags` at all and
    must never match a tags filter, regardless of the value searched."""
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["tags"].apply(records, "tags", "wireless")
    assert "gadget-3" not in {r.id for r in result}


def test_contains_filter_empty_params_is_noop(gadgets_config_and_filters, ingested_gadgets):
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    result = filters["tags"].apply(records, "tags", [])
    assert {r.id for r in result} == {r.id for r in records}


# ---------------------------------------------------------------------------
# Malformed config rejected with a clear message
# ---------------------------------------------------------------------------


def test_malformed_config_rejected_with_clear_message(tmp_path):
    """DoD edge case: a config declaring an operation that doesn't exist
    for a field's type ('contains' on 'bool') must be rejected at load
    time, with a message naming the field, the bad operation, the type,
    and what IS allowed -- not a bare stack trace."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_MALFORMED_CONFIG_YAML)

    with pytest.raises(ConfigLoadError) as exc_info:
        load_filters(config_path)

    message = str(exc_info.value)
    assert "in_stock" in message
    assert "contains" in message
    assert "bool" in message
    assert "equality" in message  # the allowed alternative is named


# ---------------------------------------------------------------------------
# The whole pipeline in one pass, combining several fields at once
# ---------------------------------------------------------------------------


def test_end_to_end_combined_filters(gadgets_config_and_filters, ingested_gadgets):
    """Apply more than one field's filter in sequence, as a real search
    request would (AND semantics across fields, orchestrated by the
    caller -- see docs/filtering.md §7)."""
    _, filters = gadgets_config_and_filters
    records = ingested_gadgets.valid_documents

    step1 = filters["category"].apply(records, "category", "peripherals")
    step2 = filters["in_stock"].apply(step1, "in_stock", True)

    assert {r.id for r in step2} == {"gadget-1"}