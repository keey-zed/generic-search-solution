import pytest

from app.core.config.loader import ConfigLoadError
from app.core.config.models import (
    BrandingConfig,
    FilterFieldConfig,
    FrontendConfig,
    SearchConfig,
    UseCaseConfig,
)
from app.core.filtering.config_loader import build_filters_from_config, load_filters
from app.core.filtering.filters import ContainsFilter, EqualityFilter, RangeFilter
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument


def _minimal_config(filters: dict[str, FilterFieldConfig]) -> UseCaseConfig:
    return UseCaseConfig(
        schema_version=1,
        filters=filters,
        search=SearchConfig(),
        frontend=FrontendConfig(branding=BrandingConfig(title="Test")),
    )


def doc(id_, **metadata):
    return NormalizedDocument(id=id_, text=f"text of {id_}", metadata=metadata)


# ---------------------------------------------------------------------------
# build_filters_from_config — programmatic UseCaseConfig
# ---------------------------------------------------------------------------


def test_builds_equality_filter_for_string_field():
    config = _minimal_config(
        {"doctype": FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality")}
    )
    filters = build_filters_from_config(config)
    assert isinstance(filters["doctype"], EqualityFilter)
    assert filters["doctype"].field_type == MetadataFieldType.STRING


def test_builds_range_filter_for_date_field():
    config = _minimal_config(
        {"pub_date": FilterFieldConfig(type=MetadataFieldType.DATE, operation="range")}
    )
    filters = build_filters_from_config(config)
    assert isinstance(filters["pub_date"], RangeFilter)
    assert filters["pub_date"].field_type == MetadataFieldType.DATE


def test_builds_contains_filter_for_list_field_with_item_type():
    config = _minimal_config(
        {
            "subjects": FilterFieldConfig(
                type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING, operation="contains"
            )
        }
    )
    filters = build_filters_from_config(config)
    assert isinstance(filters["subjects"], ContainsFilter)
    assert filters["subjects"].field_type == MetadataFieldType.LIST
    assert filters["subjects"].item_type == MetadataFieldType.STRING


def test_builds_multiple_filters_keyed_by_field_name():
    config = _minimal_config(
        {
            "doctype": FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"),
            "pub_date": FilterFieldConfig(type=MetadataFieldType.DATE, operation="range"),
            "subjects": FilterFieldConfig(
                type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING, operation="contains"
            ),
        }
    )
    filters = build_filters_from_config(config)
    assert set(filters.keys()) == {"doctype", "pub_date", "subjects"}


def test_empty_filters_config_yields_empty_dict():
    config = _minimal_config({})
    assert build_filters_from_config(config) == {}


def test_built_filters_actually_filter_records():
    config = _minimal_config(
        {"doctype": FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality")}
    )
    filters = build_filters_from_config(config)
    records = [doc("d1", doctype="dahir"), doc("d2", doctype="marsoum")]
    result = filters["doctype"].apply(records, "doctype", "dahir")
    assert [r.id for r in result] == ["d1"]


# ---------------------------------------------------------------------------
# Incompatible type/operation is already rejected at config validation,
# before build_filters_from_config is even reached
# ---------------------------------------------------------------------------


def test_incompatible_type_operation_rejected_at_config_construction():
    """This is the fail-fast requirement from the task: an invalid
    (type, operation) pairing must be caught when the config is built/
    parsed, not when build_filters_from_config or apply() runs."""
    with pytest.raises(Exception, match="not compatible"):
        FilterFieldConfig(type=MetadataFieldType.INT, operation="contains")


# ---------------------------------------------------------------------------
# load_filters — full file round trip
# ---------------------------------------------------------------------------


_VALID_YAML = """
schema_version: 1
filters:
  doctype:
    type: string
    operation: equality
  pub_date:
    type: date
    operation: range
  subjects:
    type: list
    item_type: string
    operation: contains
search: {}
frontend:
  branding:
    title: "Test Project"
"""

_INVALID_YAML_BAD_OPERATION = """
schema_version: 1
filters:
  page_count:
    type: int
    operation: contains
search: {}
frontend:
  branding:
    title: "Test Project"
"""


def test_load_filters_from_yaml_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_VALID_YAML)

    config, filters = load_filters(config_path)

    assert config.schema_version == 1
    assert isinstance(filters["doctype"], EqualityFilter)
    assert isinstance(filters["pub_date"], RangeFilter)
    assert isinstance(filters["subjects"], ContainsFilter)


def test_load_filters_result_usable_end_to_end(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_VALID_YAML)

    _, filters = load_filters(config_path)

    records = [
        doc("d1", doctype="dahir", subjects=["finance"]),
        doc("d2", doctype="marsoum", subjects=["health"]),
    ]
    result = filters["doctype"].apply(records, "doctype", "dahir")
    assert [r.id for r in result] == ["d1"]

    result2 = filters["subjects"].apply(records, "subjects", "health")
    assert [r.id for r in result2] == ["d2"]


def test_load_filters_fails_fast_on_incompatible_operation(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_INVALID_YAML_BAD_OPERATION)

    with pytest.raises(ConfigLoadError, match="not compatible"):
        load_filters(config_path)


def test_load_filters_missing_file_raises_config_load_error(tmp_path):
    with pytest.raises(ConfigLoadError, match="not found"):
        load_filters(tmp_path / "does-not-exist.yaml")


# ---------------------------------------------------------------------------
# Integration with the real project config already in the repo
# ---------------------------------------------------------------------------


def test_load_filters_against_real_legal_config():
    config, filters = load_filters("app/custom/legal/config.yaml")
    assert filters  # at least one filter declared
    for name, field_cfg in config.filters.items():
        assert name in filters
        assert filters[name].field_type == field_cfg.type