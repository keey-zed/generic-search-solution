from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.config.loader import ConfigLoadError, load_use_case_config
from app.core.config.models import (
    ALLOWED_CONTROLS,
    DEFAULT_CONTROL,
    SUPPORTED_SCHEMA_VERSIONS,
    FilterFieldConfig,
    PaginationConfig,
    RankingConfig,
    SearchConfig,
    UseCaseConfig,
)
from app.core.schema.metadata_types import FILTER_OPERATION_COMPATIBILITY, MetadataFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def minimal_valid_dict(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "filters": {
            "title": {"type": "string", "operation": "contains"},
        },
        "search": {},
        "frontend": {
            "branding": {"title": "Test App"},
            "filters": {
                "title": {"label": "Title", "order": 1},
            },
        },
    }
    base.update(overrides)
    return base


def write_yaml(tmp_path: Path, data: dict, filename: str = "config.yaml") -> Path:
    p = tmp_path / filename
    p.write_text(yaml.safe_dump(data))
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_minimal_valid_config_parses():
    cfg = UseCaseConfig.model_validate(minimal_valid_dict())
    assert cfg.schema_version == 1
    assert "title" in cfg.filters


def test_empty_filters_is_valid():
    """A project doing pure semantic/lexical search with no metadata
    filters at all is legitimate."""
    d = minimal_valid_dict()
    d["filters"] = {}
    d["frontend"]["filters"] = {}
    cfg = UseCaseConfig.model_validate(d)
    assert cfg.filters == {}


def test_search_defaults_apply_when_omitted():
    cfg = UseCaseConfig.model_validate(minimal_valid_dict())
    assert cfg.search.semantic.enabled is True
    assert cfg.search.lexical.enabled is True
    assert cfg.search.pagination.default_page_size == 20


def test_frontend_control_auto_resolves_when_omitted():
    cfg = UseCaseConfig.model_validate(minimal_valid_dict())
    assert cfg.frontend.filters["title"].control == "text"


def test_to_metadata_schema_round_trip():
    cfg = UseCaseConfig.model_validate(minimal_valid_dict())
    schema = cfg.to_metadata_schema()
    assert len(schema) == 1
    assert schema[0].name == "title"
    assert schema[0].type == MetadataFieldType.STRING


# ---------------------------------------------------------------------------
# schema_version
# ---------------------------------------------------------------------------


def test_missing_schema_version_via_loader_raises_config_load_error(tmp_path):
    d = minimal_valid_dict()
    del d["schema_version"]
    path = write_yaml(tmp_path, d)
    with pytest.raises(ConfigLoadError, match="schema_version"):
        load_use_case_config(path)


def test_missing_schema_version_via_pydantic_raises_validation_error():
    d = minimal_valid_dict()
    del d["schema_version"]
    with pytest.raises(ValidationError):
        UseCaseConfig.model_validate(d)


def test_unsupported_schema_version_rejected():
    d = minimal_valid_dict(schema_version=999)
    with pytest.raises(ValidationError, match="not supported"):
        UseCaseConfig.model_validate(d)


def test_all_supported_versions_are_accepted():
    for v in SUPPORTED_SCHEMA_VERSIONS:
        d = minimal_valid_dict(schema_version=v)
        UseCaseConfig.model_validate(d)  # must not raise


# ---------------------------------------------------------------------------
# filters: — type/operation compatibility
# ---------------------------------------------------------------------------


def test_incompatible_operation_rejected():
    with pytest.raises(ValidationError, match="not compatible"):
        FilterFieldConfig(type="bool", operation="contains")


@pytest.mark.parametrize(
    "field_type,operation",
    [
        (t.value, op)
        for t, ops in FILTER_OPERATION_COMPATIBILITY.items()
        for op in ops
    ],
)
def test_every_compatible_type_operation_pair_is_accepted(field_type, operation):
    kwargs = {"type": field_type, "operation": operation}
    if field_type == "list":
        kwargs["item_type"] = "string"
    FilterFieldConfig(**kwargs)  # must not raise


def test_list_type_without_item_type_rejected():
    with pytest.raises(ValidationError, match="item_type is required"):
        FilterFieldConfig(type="list", operation="contains")


def test_list_type_with_nested_list_item_type_rejected():
    with pytest.raises(ValidationError, match="scalar type"):
        FilterFieldConfig(type="list", item_type="list", operation="contains")


def test_non_list_type_with_item_type_rejected():
    with pytest.raises(ValidationError, match="only be set when type"):
        FilterFieldConfig(type="string", item_type="string", operation="contains")


def test_invalid_field_name_rejected():
    d = minimal_valid_dict()
    d["filters"] = {"bad name!": {"type": "string", "operation": "contains"}}
    d["frontend"]["filters"] = {}
    with pytest.raises(ValidationError, match="invalid"):
        UseCaseConfig.model_validate(d)


def test_valid_field_name_with_underscore_and_digits_accepted():
    d = minimal_valid_dict()
    d["filters"] = {"field_2_name": {"type": "string", "operation": "contains"}}
    d["frontend"]["filters"] = {}
    UseCaseConfig.model_validate(d)  # must not raise


def test_unknown_top_level_key_rejected():
    d = minimal_valid_dict(extra_bogus_key="surprise")
    with pytest.raises(ValidationError):
        UseCaseConfig.model_validate(d)


def test_unknown_key_inside_filter_entry_rejected():
    d = minimal_valid_dict()
    d["filters"]["title"]["typo_field"] = "oops"
    with pytest.raises(ValidationError):
        UseCaseConfig.model_validate(d)


# ---------------------------------------------------------------------------
# frontend: cross-validation against filters
# ---------------------------------------------------------------------------


def test_frontend_filter_referencing_unknown_field_rejected():
    d = minimal_valid_dict()
    d["frontend"]["filters"]["nonexistent_field"] = {"label": "X", "order": 5}
    with pytest.raises(ValidationError, match="no matching entry"):
        UseCaseConfig.model_validate(d)


def test_frontend_control_incompatible_with_field_rejected():
    d = minimal_valid_dict()
    d["filters"]["title"] = {"type": "bool", "operation": "equality"}
    d["frontend"]["filters"]["title"] = {"label": "Title", "order": 1, "control": "date_range"}
    with pytest.raises(ValidationError, match="not valid"):
        UseCaseConfig.model_validate(d)


def test_frontend_control_compatible_override_accepted():
    d = minimal_valid_dict()
    d["filters"]["title"] = {"type": "string", "operation": "equality"}
    d["frontend"]["filters"]["title"] = {"label": "Title", "order": 1, "control": "radio"}
    cfg = UseCaseConfig.model_validate(d)
    assert cfg.frontend.filters["title"].control == "radio"


def test_duplicate_frontend_order_rejected():
    d = minimal_valid_dict()
    d["filters"]["subtitle_field"] = {"type": "string", "operation": "contains"}
    d["frontend"]["filters"]["subtitle_field"] = {"label": "Sub", "order": 1}  # same order as "title"
    with pytest.raises(ValidationError, match="duplicate 'order'"):
        UseCaseConfig.model_validate(d)


def test_filter_not_exposed_in_frontend_is_valid_backend_only_filter():
    """A field declared under filters: with no frontend.filters entry is
    legitimate — filterable via API, hidden from UI (opt-in exposure)."""
    d = minimal_valid_dict()
    d["filters"]["internal_flag"] = {"type": "bool", "operation": "equality"}
    # deliberately not added to frontend.filters
    cfg = UseCaseConfig.model_validate(d)
    assert "internal_flag" in cfg.filters
    assert "internal_flag" not in cfg.frontend.filters


def test_blank_label_rejected():
    d = minimal_valid_dict()
    d["frontend"]["filters"]["title"]["label"] = "   "
    with pytest.raises(ValidationError, match="blank"):
        UseCaseConfig.model_validate(d)


def test_every_default_control_pair_covers_all_compatible_type_operations():
    """Guards against a new (type, operation) combo being added to
    FILTER_OPERATION_COMPATIBILITY without a matching DEFAULT_CONTROL /
    ALLOWED_CONTROLS entry — which would silently break control
    resolution for any config using that combo."""
    for field_type, ops in FILTER_OPERATION_COMPATIBILITY.items():
        for op in ops:
            key = (field_type, op)
            assert key in DEFAULT_CONTROL, f"missing DEFAULT_CONTROL for {key}"
            assert key in ALLOWED_CONTROLS, f"missing ALLOWED_CONTROLS for {key}"
            assert DEFAULT_CONTROL[key] in ALLOWED_CONTROLS[key], (
                f"DEFAULT_CONTROL[{key}] = {DEFAULT_CONTROL[key]!r} is not itself "
                f"in ALLOWED_CONTROLS[{key}] = {ALLOWED_CONTROLS[key]!r}"
            )


# ---------------------------------------------------------------------------
# branding
# ---------------------------------------------------------------------------


def test_blank_title_rejected():
    d = minimal_valid_dict()
    d["frontend"]["branding"]["title"] = "  "
    with pytest.raises(ValidationError, match="blank"):
        UseCaseConfig.model_validate(d)


def test_valid_hex_color_accepted():
    d = minimal_valid_dict()
    d["frontend"]["branding"]["primary_color"] = "#AABBCC"
    UseCaseConfig.model_validate(d)  # must not raise


@pytest.mark.parametrize("bad_color", ["red", "#ABC", "#GGGGGG", "123456", "#12345"])
def test_invalid_hex_color_rejected(bad_color):
    d = minimal_valid_dict()
    d["frontend"]["branding"]["primary_color"] = bad_color
    with pytest.raises(ValidationError, match="hex color"):
        UseCaseConfig.model_validate(d)


# ---------------------------------------------------------------------------
# search:
# ---------------------------------------------------------------------------


def test_both_search_modes_disabled_rejected():
    d = minimal_valid_dict()
    d["search"] = {"semantic": {"enabled": False}, "lexical": {"enabled": False}}
    with pytest.raises(ValidationError, match="at least one"):
        UseCaseConfig.model_validate(d)


def test_only_semantic_enabled_is_valid():
    d = minimal_valid_dict()
    d["search"] = {"semantic": {"enabled": True}, "lexical": {"enabled": False}}
    UseCaseConfig.model_validate(d)  # must not raise


def test_ranking_weights_default_to_half_and_half():
    cfg = SearchConfig.model_validate({})
    assert cfg.ranking.weights.semantic == 0.5
    assert cfg.ranking.weights.lexical == 0.5


def test_ranking_weights_both_zero_rejected():
    with pytest.raises(ValidationError, match="cannot both be 0"):
        RankingConfig.model_validate({"weights": {"semantic": 0, "lexical": 0}})


def test_negative_ranking_weight_rejected():
    with pytest.raises(ValidationError):
        RankingConfig.model_validate({"weights": {"semantic": -0.1, "lexical": 0.5}})


def test_pagination_default_exceeds_max_rejected():
    with pytest.raises(ValidationError, match="cannot exceed"):
        PaginationConfig.model_validate({"default_page_size": 200, "max_page_size": 100})


def test_pagination_default_equal_to_max_is_valid():
    PaginationConfig.model_validate({"default_page_size": 100, "max_page_size": 100})


def test_pagination_zero_page_size_rejected():
    with pytest.raises(ValidationError):
        PaginationConfig.model_validate({"default_page_size": 0})


def test_unsupported_multi_query_combination_rejected():
    d = minimal_valid_dict()
    d["search"] = {"semantic": {"multi_query_combination": "median"}}
    with pytest.raises(ValidationError):
        UseCaseConfig.model_validate(d)


def test_unsupported_ranking_strategy_rejected():
    d = minimal_valid_dict()
    d["search"] = {"ranking": {"strategy": "borda_count"}}
    with pytest.raises(ValidationError):
        UseCaseConfig.model_validate(d)


# ---------------------------------------------------------------------------
# loader: file/YAML-level failures
# ---------------------------------------------------------------------------


def test_loader_missing_file_raises(tmp_path):
    with pytest.raises(ConfigLoadError, match="not found"):
        load_use_case_config(tmp_path / "does_not_exist.yaml")


def test_loader_directory_instead_of_file_raises(tmp_path):
    with pytest.raises(ConfigLoadError, match="not a file"):
        load_use_case_config(tmp_path)


def test_loader_empty_file_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    with pytest.raises(ConfigLoadError, match="empty"):
        load_use_case_config(p)


def test_loader_invalid_yaml_syntax_raises(tmp_path):
    p = tmp_path / "broken.yaml"
    p.write_text("filters: [this is: not, valid: yaml: at: all")
    with pytest.raises(ConfigLoadError, match="invalid YAML syntax"):
        load_use_case_config(p)


def test_loader_non_mapping_root_raises(tmp_path):
    p = tmp_path / "list_root.yaml"
    p.write_text(yaml.safe_dump(["not", "a", "mapping"]))
    with pytest.raises(ConfigLoadError, match="mapping"):
        load_use_case_config(p)


def test_loader_scalar_root_raises(tmp_path):
    p = tmp_path / "scalar_root.yaml"
    p.write_text("just a string")
    with pytest.raises(ConfigLoadError, match="mapping"):
        load_use_case_config(p)


def test_loader_valid_config_loads_successfully(tmp_path):
    path = write_yaml(tmp_path, minimal_valid_dict())
    cfg = load_use_case_config(path)
    assert isinstance(cfg, UseCaseConfig)
    assert cfg.schema_version == 1


def test_loader_wraps_pydantic_validation_error_with_file_name(tmp_path):
    d = minimal_valid_dict(schema_version=999)
    path = write_yaml(tmp_path, d, filename="bad_version.yaml")
    with pytest.raises(ConfigLoadError, match="bad_version.yaml"):
        load_use_case_config(path)


# ---------------------------------------------------------------------------
# The real reference example
# ---------------------------------------------------------------------------


def test_legal_reference_config_loads_and_produces_expected_metadata_schema():
    path = Path(__file__).resolve().parent.parent / "app" / "custom" / "legal" / "config.yaml"
    cfg = load_use_case_config(path)

    assert set(cfg.filters.keys()) == {
        "document_type", "publication_date", "promulgation_date", "subjects", "title",
    }
    # promulgation_date deliberately has no frontend entry (backend-only filter)
    assert "promulgation_date" not in cfg.frontend.filters
    assert cfg.frontend.filters["document_type"].control == "dropdown"
    assert cfg.frontend.filters["subjects"].control == "multi_select"

    schema = cfg.to_metadata_schema()
    names = {f.name for f in schema}
    assert names == set(cfg.filters.keys())
    doctype_field = next(f for f in schema if f.name == "document_type")
    assert doctype_field.required is True
