"""
app/core/filtering/config_loader.py

Phase 1, Track B, task 3: turn a validated `UseCaseConfig` into the
actual runtime `Filter` objects search/filtering code uses.

Almost everything this task asked for already exists elsewhere, and this
module deliberately does not redo any of it:

  - Parsing a config.yaml file and validating it against the Phase 0
    schema: `app/core/config/loader.py` (`load_use_case_config`).
  - Failing fast, AT CONFIG-LOAD TIME, if a config declares an operation
    incompatible with a field's type (e.g. `contains` on an `int`
    field): `FilterFieldConfig.validate_shape_and_operation`
    (`app/core/config/models.py`) already raises for this, reusing the
    exact same `is_operation_compatible()` check
    `app/core/filtering/base.py`'s `Filter.__init__` also uses -- one
    compatibility rule, checked in both places, never two copies that
    could quietly drift apart.

What was missing, and what this module adds, is the last step: turning
each validated `FilterFieldConfig` into the concrete `Filter` instance
(task 2) that implements its declared operation, via the registry (task
4) -- so this code, and everything downstream of it, never has an
if/elif over operation names.

    config.yaml
        |
        v
  load_use_case_config()          (already existed)  -> UseCaseConfig
        |
        v
  build_filters_from_config()     (this module)       -> dict[field_name, Filter]
        |
        v
  filtering/search code calls filters[field_name].apply(records, field_name, params)
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from app.core.config.loader import ConfigLoadError, load_use_case_config
from app.core.config.models import UseCaseConfig
from app.core.filtering.base import Filter, FilterError
from app.core.filtering.registry import get_filter_class


def build_filters_from_config(config: UseCaseConfig) -> dict[str, Filter]:
    """Instantiate one `Filter` per field declared under `config.filters`,
    keyed by field name.

    By the time a `UseCaseConfig` exists, its own validation has already
    guaranteed every field's (type, operation) pair is compatible and
    every LIST field has an item_type set correctly -- so `Filter`'s own
    construction-time checks (`app/core/filtering/base.py`) are not
    expected to fail here. They still run regardless (nothing bypasses
    them); if one somehow does fail, it's re-raised as `ConfigLoadError`
    rather than a bare `FilterError`, so a caller of this function gets
    ONE consistent error type for "this config could not be turned into
    working filters", no matter which layer actually caught the problem.
    """
    filters: dict[str, Filter] = {}
    for name, field_cfg in config.filters.items():
        try:
            filter_cls = get_filter_class(field_cfg.operation)
            filters[name] = filter_cls(field_type=field_cfg.type, item_type=field_cfg.item_type)
        except FilterError as exc:
            raise ConfigLoadError(
                f"filters['{name}']: could not build a filter for operation "
                f"'{field_cfg.operation}' on type '{field_cfg.type.value}': {exc}"
            ) from exc
    return filters


def load_filters(path: Union[str, Path]) -> tuple[UseCaseConfig, dict[str, Filter]]:
    """Convenience entry point for a project's startup code: load
    config.yaml, validate it, and build every declared filter, in one
    call.

    Raises `ConfigLoadError` for any problem at any stage -- file not
    found, invalid YAML syntax, schema validation (including an
    incompatible type/operation pairing), or filter construction --
    always with a message naming the specific field/problem, never a
    bare stack trace.
    """
    config = load_use_case_config(path)
    filters = build_filters_from_config(config)
    return config, filters