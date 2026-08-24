from datetime import date

import pytest
from pydantic import ValidationError

from app.core.schema.document import DocumentRecord
from app.core.schema.metadata_types import (
    FILTER_OPERATION_COMPATIBILITY,
    MetadataFieldDef,
    MetadataFieldType,
    is_operation_compatible,
    normalize_metadata,
    validate_document_batch,
)

# ---------------------------------------------------------------------------
# MetadataFieldDef construction rules
# ---------------------------------------------------------------------------


def test_list_type_requires_item_type():
    with pytest.raises(ValidationError):
        MetadataFieldDef(name="tags", type=MetadataFieldType.LIST)


def test_non_list_type_forbids_item_type():
    with pytest.raises(ValidationError):
        MetadataFieldDef(name="title", type=MetadataFieldType.STRING, item_type=MetadataFieldType.STRING)


def test_nested_list_item_type_rejected():
    with pytest.raises(ValidationError):
        MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.LIST)


def test_blank_field_name_rejected():
    with pytest.raises(ValidationError):
        MetadataFieldDef(name="  ", type=MetadataFieldType.STRING)


def test_valid_list_field():
    f = MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)
    assert f.item_type == MetadataFieldType.STRING


# ---------------------------------------------------------------------------
# Scalar coercion — STRING
# ---------------------------------------------------------------------------


def test_string_field_accepts_str():
    typed, errors = normalize_metadata("id1", {"title": "hello"}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING)])
    assert errors == []
    assert typed["title"] == "hello"


def test_string_field_rejects_int():
    typed, errors = normalize_metadata("id1", {"title": 123}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING)])
    assert len(errors) == 1
    assert "expected string" in errors[0].message
    assert typed["title"] is None


# ---------------------------------------------------------------------------
# Scalar coercion — INT (including the bool trap)
# ---------------------------------------------------------------------------


def test_int_field_accepts_int():
    typed, errors = normalize_metadata("id1", {"n": 42}, [MetadataFieldDef(name="n", type=MetadataFieldType.INT)])
    assert errors == []
    assert typed["n"] == 42


def test_int_field_rejects_bool_even_though_bool_is_a_python_int_subclass():
    typed, errors = normalize_metadata("id1", {"n": True}, [MetadataFieldDef(name="n", type=MetadataFieldType.INT)])
    assert len(errors) == 1
    assert "expected int, got bool" in errors[0].message


def test_int_field_rejects_float_even_when_integral():
    typed, errors = normalize_metadata("id1", {"n": 5.0}, [MetadataFieldDef(name="n", type=MetadataFieldType.INT)])
    assert len(errors) == 1
    assert typed["n"] is None


def test_int_field_accepts_negative():
    typed, errors = normalize_metadata("id1", {"n": -7}, [MetadataFieldDef(name="n", type=MetadataFieldType.INT)])
    assert errors == []
    assert typed["n"] == -7


# ---------------------------------------------------------------------------
# Scalar coercion — FLOAT
# ---------------------------------------------------------------------------


def test_float_field_accepts_float():
    typed, errors = normalize_metadata("id1", {"n": 3.14}, [MetadataFieldDef(name="n", type=MetadataFieldType.FLOAT)])
    assert errors == []
    assert typed["n"] == 3.14


def test_float_field_upcasts_int():
    typed, errors = normalize_metadata("id1", {"n": 3}, [MetadataFieldDef(name="n", type=MetadataFieldType.FLOAT)])
    assert errors == []
    assert typed["n"] == 3.0
    assert isinstance(typed["n"], float)


def test_float_field_rejects_bool():
    typed, errors = normalize_metadata("id1", {"n": False}, [MetadataFieldDef(name="n", type=MetadataFieldType.FLOAT)])
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Scalar coercion — BOOL
# ---------------------------------------------------------------------------


def test_bool_field_accepts_bool():
    typed, errors = normalize_metadata("id1", {"flag": True}, [MetadataFieldDef(name="flag", type=MetadataFieldType.BOOL)])
    assert errors == []
    assert typed["flag"] is True


def test_bool_field_rejects_int_zero_or_one():
    typed, errors = normalize_metadata("id1", {"flag": 1}, [MetadataFieldDef(name="flag", type=MetadataFieldType.BOOL)])
    assert len(errors) == 1


def test_bool_field_rejects_string_true():
    typed, errors = normalize_metadata("id1", {"flag": "true"}, [MetadataFieldDef(name="flag", type=MetadataFieldType.BOOL)])
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Scalar coercion — DATE
# ---------------------------------------------------------------------------


def test_date_field_accepts_iso_date():
    typed, errors = normalize_metadata("id1", {"d": "2025-01-15"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert errors == []
    assert typed["d"] == date(2025, 1, 15)


def test_date_field_rejects_slash_format():
    typed, errors = normalize_metadata("id1", {"d": "2025/01/15"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert len(errors) == 1


def test_date_field_rejects_datetime_with_time_component():
    typed, errors = normalize_metadata("id1", {"d": "2025-01-15T10:00:00"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert len(errors) == 1


def test_date_field_rejects_invalid_calendar_date():
    """Feb 30 doesn't exist — must be caught, not silently normalized to Mar 2."""
    typed, errors = normalize_metadata("id1", {"d": "2024-02-30"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert len(errors) == 1
    assert "invalid calendar date" in errors[0].message


def test_date_field_handles_leap_year_correctly():
    typed, errors = normalize_metadata("id1", {"d": "2024-02-29"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert errors == []
    assert typed["d"] == date(2024, 2, 29)


def test_date_field_rejects_non_leap_year_feb_29():
    typed, errors = normalize_metadata("id1", {"d": "2023-02-29"}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert len(errors) == 1


def test_date_field_rejects_non_string():
    typed, errors = normalize_metadata("id1", {"d": 20250115}, [MetadataFieldDef(name="d", type=MetadataFieldType.DATE)])
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# required vs optional / missing vs null
# ---------------------------------------------------------------------------


def test_required_field_missing_is_error():
    typed, errors = normalize_metadata("id1", {}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING, required=True)])
    assert len(errors) == 1
    assert "required" in errors[0].message
    assert typed["title"] is None


def test_required_field_explicit_null_is_error():
    typed, errors = normalize_metadata("id1", {"title": None}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING, required=True)])
    assert len(errors) == 1


def test_optional_field_missing_normalizes_to_none_without_error():
    typed, errors = normalize_metadata("id1", {}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING, required=False)])
    assert errors == []
    assert typed["title"] is None


def test_optional_field_explicit_null_normalizes_to_none_without_error():
    typed, errors = normalize_metadata("id1", {"title": None}, [MetadataFieldDef(name="title", type=MetadataFieldType.STRING)])
    assert errors == []
    assert typed["title"] is None


def test_every_declared_field_present_in_output_even_if_absent_from_raw():
    schema = [
        MetadataFieldDef(name="a", type=MetadataFieldType.STRING),
        MetadataFieldDef(name="b", type=MetadataFieldType.INT),
    ]
    typed, errors = normalize_metadata("id1", {"a": "x"}, schema)
    assert set(typed.keys()) >= {"a", "b"}
    assert typed["b"] is None


# ---------------------------------------------------------------------------
# LIST fields
# ---------------------------------------------------------------------------


def test_list_field_of_strings():
    schema = [MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)]
    typed, errors = normalize_metadata("id1", {"tags": ["a", "b"]}, schema)
    assert errors == []
    assert typed["tags"] == ["a", "b"]


def test_list_field_of_dates():
    schema = [MetadataFieldDef(name="refs", type=MetadataFieldType.LIST, item_type=MetadataFieldType.DATE)]
    typed, errors = normalize_metadata("id1", {"refs": ["2020-01-01", "2021-06-15"]}, schema)
    assert errors == []
    assert typed["refs"] == [date(2020, 1, 1), date(2021, 6, 15)]


def test_list_field_rejects_non_list_raw_value():
    schema = [MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)]
    typed, errors = normalize_metadata("id1", {"tags": "not-a-list"}, schema)
    assert len(errors) == 1
    assert typed["tags"] is None


def test_list_field_with_one_bad_item_reports_that_item_and_nulls_whole_field():
    """A partially-typed list is never returned — either the whole list
    normalizes cleanly or the field comes back None with an error, so a
    range/contains filter downstream never sees a mixed-type list."""
    schema = [MetadataFieldDef(name="years", type=MetadataFieldType.LIST, item_type=MetadataFieldType.INT)]
    typed, errors = normalize_metadata("id1", {"years": [2020, "oops", 2022]}, schema)
    assert len(errors) == 1
    assert "years[1]" in errors[0].field
    assert typed["years"] is None


def test_list_field_empty_list_is_valid():
    schema = [MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)]
    typed, errors = normalize_metadata("id1", {"tags": []}, schema)
    assert errors == []
    assert typed["tags"] == []


def test_list_field_missing_and_optional_normalizes_to_none_not_empty_list():
    schema = [MetadataFieldDef(name="tags", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING)]
    typed, errors = normalize_metadata("id1", {}, schema)
    assert errors == []
    assert typed["tags"] is None  # explicitly None, not [] — documented choice


# ---------------------------------------------------------------------------
# Unknown / undeclared fields
# ---------------------------------------------------------------------------


def test_undeclared_field_passthrough_by_default():
    typed, errors = normalize_metadata("id1", {"surprise": "value"}, [])
    assert errors == []
    assert typed["surprise"] == "value"


def test_undeclared_field_strict_mode_errors():
    typed, errors = normalize_metadata("id1", {"surprise": "value"}, [], unknown_field_policy="strict")
    assert len(errors) == 1
    assert "surprise" in errors[0].field


def test_invalid_unknown_field_policy_raises():
    with pytest.raises(ValueError):
        normalize_metadata("id1", {}, [], unknown_field_policy="bogus")


def test_multiple_errors_collected_in_one_pass_not_just_the_first():
    schema = [
        MetadataFieldDef(name="a", type=MetadataFieldType.INT),
        MetadataFieldDef(name="b", type=MetadataFieldType.DATE),
    ]
    typed, errors = normalize_metadata("id1", {"a": "not-int", "b": "not-a-date"}, schema)
    assert len(errors) == 2
    fields_with_errors = {e.field for e in errors}
    assert fields_with_errors == {"a", "b"}


# ---------------------------------------------------------------------------
# Batch validation
# ---------------------------------------------------------------------------


def test_batch_validation_separates_valid_and_invalid_records():
    schema = [MetadataFieldDef(name="year", type=MetadataFieldType.INT)]
    records = [
        DocumentRecord(id="ok-1", text="t", metadata={"year": 2020}),
        DocumentRecord(id="bad-1", text="t", metadata={"year": "nope"}),
    ]
    result = validate_document_batch(records, schema)
    assert len(result.valid_documents) == 1
    assert result.valid_documents[0].id == "ok-1"
    assert len(result.record_errors) == 1
    assert result.record_errors[0].record_id == "bad-1"
    assert not result.is_clean


def test_batch_validation_detects_duplicate_ids_and_excludes_all_copies():
    records = [
        DocumentRecord(id="dup", text="first", metadata={}),
        DocumentRecord(id="dup", text="second", metadata={}),
        DocumentRecord(id="unique", text="fine", metadata={}),
    ]
    result = validate_document_batch(records, [])
    assert result.duplicate_ids == ["dup"]
    valid_ids = {d.id for d in result.valid_documents}
    assert "dup" not in valid_ids
    assert "unique" in valid_ids
    assert not result.is_clean


def test_batch_validation_clean_when_no_errors_and_no_duplicates():
    records = [DocumentRecord(id="a", text="t", metadata={})]
    result = validate_document_batch(records, [])
    assert result.is_clean
    assert "1 valid" in result.summary


def test_batch_validation_empty_batch_is_clean():
    result = validate_document_batch([], [])
    assert result.is_clean
    assert result.valid_documents == []


# ---------------------------------------------------------------------------
# Filter operation compatibility matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_type,operation,expected",
    [
        (MetadataFieldType.STRING, "equality", True),
        (MetadataFieldType.STRING, "contains", True),
        (MetadataFieldType.STRING, "range", False),
        (MetadataFieldType.DATE, "range", True),
        (MetadataFieldType.DATE, "contains", False),
        (MetadataFieldType.INT, "range", True),
        (MetadataFieldType.INT, "contains", False),
        (MetadataFieldType.FLOAT, "range", True),
        (MetadataFieldType.BOOL, "equality", True),
        (MetadataFieldType.BOOL, "range", False),
        (MetadataFieldType.BOOL, "contains", False),
        (MetadataFieldType.LIST, "contains", True),
        (MetadataFieldType.LIST, "equality", False),
        (MetadataFieldType.LIST, "range", False),
    ],
)
def test_filter_compatibility_matrix(field_type, operation, expected):
    assert is_operation_compatible(field_type, operation) == expected


def test_every_field_type_has_a_compatibility_entry():
    """Guards against someone adding a new MetadataFieldType and forgetting
    to declare its allowed operations — this would otherwise silently
    make every operation incompatible with the new type."""
    for ft in MetadataFieldType:
        assert ft in FILTER_OPERATION_COMPATIBILITY, f"{ft} missing from FILTER_OPERATION_COMPATIBILITY"
