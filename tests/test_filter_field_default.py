"""
tests/test_filter_field_default.py

Source doc §5 lists "default values, where applicable" as one thing a
project's config.yaml should be able to specify -- this was missing from
`FilterFieldConfig` until now (found by checking the built schema
against the actual source document once it became available). This file
tests the addition: `FilterFieldConfig.default`, validated the same way
a record's own metadata value would be (reusing
`metadata_types._coerce_scalar`).

Scope, stated plainly: this only validates that `default` is a
well-typed value for its field's declared operation/type. Whether/how a
default is actually APPLIED (a UI pre-filling a control vs. an implicit
query constraint when a request omits the field) is deliberately left
unspecified here -- that's a decision for whatever consumes this config
(the frontend, or the orchestrator), not for the schema layer.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config.models import FilterFieldConfig
from app.core.schema.metadata_types import MetadataFieldType


# ---------------------------------------------------------------------------
# Absence / presence
# ---------------------------------------------------------------------------


def test_default_is_none_by_default():
    cfg = FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality")
    assert cfg.default is None


def test_default_none_explicitly_is_accepted():
    cfg = FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality", default=None)
    assert cfg.default is None


# ---------------------------------------------------------------------------
# equality / contains — single scalar or list of scalars
# ---------------------------------------------------------------------------


def test_default_single_string_value_for_equality():
    cfg = FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality", default="dahir")
    assert cfg.default == "dahir"


def test_default_list_of_string_values_for_equality():
    cfg = FilterFieldConfig(
        type=MetadataFieldType.STRING, operation="equality", default=["dahir", "marsoum"]
    )
    assert cfg.default == ["dahir", "marsoum"]


def test_default_bool_value():
    cfg = FilterFieldConfig(type=MetadataFieldType.BOOL, operation="equality", default=True)
    assert cfg.default is True


def test_default_int_value():
    cfg = FilterFieldConfig(type=MetadataFieldType.INT, operation="equality", default=5)
    assert cfg.default == 5


def test_default_float_value():
    cfg = FilterFieldConfig(type=MetadataFieldType.FLOAT, operation="range", default={"min": 0.5})
    assert cfg.default == {"min": 0.5}


def test_default_date_string_value():
    cfg = FilterFieldConfig(type=MetadataFieldType.DATE, operation="equality", default="2020-01-01")
    assert cfg.default == "2020-01-01"


def test_default_rejects_malformed_date_string():
    with pytest.raises(ValidationError, match="invalid for type 'date'"):
        FilterFieldConfig(type=MetadataFieldType.DATE, operation="equality", default="01/01/2020")


def test_default_rejects_wrong_type_scalar():
    with pytest.raises(ValidationError, match="invalid for type 'string'"):
        FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality", default=123)


def test_default_rejects_bool_for_int_trap():
    """isinstance(True, int) is True in Python -- must not silently pass
    as an int default, same trap _coerce_scalar already guards against."""
    with pytest.raises(ValidationError, match="invalid for type 'int'"):
        FilterFieldConfig(type=MetadataFieldType.INT, operation="equality", default=True)


def test_default_rejects_empty_list():
    with pytest.raises(ValidationError, match="must not be an empty list"):
        FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality", default=[])


def test_default_rejects_one_bad_value_in_a_list():
    with pytest.raises(ValidationError, match="invalid for type 'string'"):
        FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality", default=["ok", 5])


# ---------------------------------------------------------------------------
# LIST fields — default validated against item_type
# ---------------------------------------------------------------------------


def test_default_for_list_field_validated_against_item_type():
    cfg = FilterFieldConfig(
        type=MetadataFieldType.LIST,
        item_type=MetadataFieldType.STRING,
        operation="contains",
        default="finance",
    )
    assert cfg.default == "finance"


def test_default_for_list_field_rejects_wrong_item_type():
    with pytest.raises(ValidationError, match="invalid for type 'string'"):
        FilterFieldConfig(
            type=MetadataFieldType.LIST,
            item_type=MetadataFieldType.STRING,
            operation="contains",
            default=42,
        )


def test_default_for_list_of_int_field():
    cfg = FilterFieldConfig(
        type=MetadataFieldType.LIST,
        item_type=MetadataFieldType.INT,
        operation="contains",
        default=[2020, 2021],
    )
    assert cfg.default == [2020, 2021]


# ---------------------------------------------------------------------------
# range — {"min": ..., "max": ..., "min_inclusive": ..., "max_inclusive": ...}
# ---------------------------------------------------------------------------


def test_default_range_both_bounds():
    cfg = FilterFieldConfig(
        type=MetadataFieldType.DATE,
        operation="range",
        default={"min": "2020-01-01", "max": "2020-12-31"},
    )
    assert cfg.default == {"min": "2020-01-01", "max": "2020-12-31"}


def test_default_range_only_min_bound():
    cfg = FilterFieldConfig(type=MetadataFieldType.INT, operation="range", default={"min": 10})
    assert cfg.default == {"min": 10}


def test_default_range_with_inclusivity_flags():
    cfg = FilterFieldConfig(
        type=MetadataFieldType.INT,
        operation="range",
        default={"min": 10, "max": 20, "min_inclusive": False},
    )
    assert cfg.default["min_inclusive"] is False


def test_default_range_empty_mapping_is_allowed():
    """An empty {} default is a legal (if unusual) 'no bound restricted'
    default -- consistent with RangeFilter itself treating an empty
    params mapping as a no-op (docs/filtering.md §2)."""
    cfg = FilterFieldConfig(type=MetadataFieldType.INT, operation="range", default={})
    assert cfg.default == {}


def test_default_range_rejects_non_mapping():
    with pytest.raises(ValidationError, match="must be a mapping"):
        FilterFieldConfig(type=MetadataFieldType.INT, operation="range", default=10)


def test_default_range_rejects_unknown_key():
    with pytest.raises(ValidationError, match="unknown key"):
        FilterFieldConfig(
            type=MetadataFieldType.INT, operation="range", default={"minimum": 10}
        )


def test_default_range_rejects_bad_bound_type():
    with pytest.raises(ValidationError, match="invalid for type 'int'"):
        FilterFieldConfig(type=MetadataFieldType.INT, operation="range", default={"min": "ten"})


def test_default_range_rejects_non_bool_inclusive_flag():
    with pytest.raises(ValidationError, match="must be a boolean"):
        FilterFieldConfig(
            type=MetadataFieldType.INT, operation="range", default={"min": 1, "min_inclusive": "yes"}
        )


# ---------------------------------------------------------------------------
# Full config.yaml round trip
# ---------------------------------------------------------------------------


def test_default_survives_full_config_load(tmp_path):
    from app.core.config.loader import load_use_case_config

    config_yaml = """
schema_version: 1
filters:
  doctype:
    type: string
    operation: equality
    default: dahir
  publication_date:
    type: date
    operation: range
    default:
      min: "2020-01-01"
search: {}
frontend:
  branding:
    title: "Test"
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_yaml)
    config = load_use_case_config(path)
    assert config.filters["doctype"].default == "dahir"
    assert config.filters["publication_date"].default == {"min": "2020-01-01"}


def test_bad_default_rejected_at_config_load_time(tmp_path):
    from app.core.config.loader import ConfigLoadError, load_use_case_config

    config_yaml = """
schema_version: 1
filters:
  page_count:
    type: int
    operation: equality
    default: "not a number"
search: {}
frontend:
  branding:
    title: "Test"
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_yaml)
    with pytest.raises(ConfigLoadError, match="invalid for type 'int'"):
        load_use_case_config(path)