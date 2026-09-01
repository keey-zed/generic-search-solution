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

Phase 2 addition -- the §6 override mechanism
-----------------------------------------------
Source doc §6: "generic default -> use-case configuration -> optional
custom override." Concretely, that chain is implemented right here, at
the one place a field name turns into a live `Filter` instance:

    for each declared field:
        1. GENERIC DEFAULT   -- look the operation up in the global
                                 registry (registry.py), same as Phase 1.
        2. USE-CASE CONFIG    -- config.yaml already decided this field's
                                 `type` + `operation` (Phase 0/1); that
                                 choice is what step 1 looks up.
        3. CUSTOM OVERRIDE     -- if the caller's `custom_filters` mapping
                                 names THIS field, use that class instead
                                 of whatever step 1 would have picked.

A project's custom layer (app/custom/<project>/) is what supplies
`custom_filters`, e.g. `{"title": FuzzyTitleEqualityFilter}` -- one dict,
built once at startup and threaded through `load_filters()` /
`build_filters_from_config()`. Nothing about the override lives in the
generic registry itself (registry.py is untouched by this): a custom
override is a call-site concern, not a global one, so two different
projects forking this repo can override the same field name completely
differently without stepping on each other.

Deliberately NOT changed to make this possible: the override class still
declares its own `operation: ClassVar[str]` and is still constructed via
`Filter.__init__(field_type, item_type)` (base.py), so it still gets
`Filter.__init__`'s own field_type/operation compatibility check for
free -- an override cannot bypass "contains is not valid on bool" simply
by being an override. The one additional check this module adds is that
the override's declared `operation` must match what the field's own
`config.yaml` entry declares (`field_cfg.operation`) -- an override for
"title" must still behave like whatever operation "title" was configured
as, or the config and the runtime behavior would silently disagree about
what kind of filter "title" even is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Type, Union

from app.core.config.loader import ConfigLoadError, load_use_case_config
from app.core.config.models import UseCaseConfig
from app.core.filtering.base import Filter, FilterError
from app.core.filtering.registry import get_filter_class

# field_name -> Filter subclass to use INSTEAD OF the generic registry
# lookup for that field. See module docstring, "Phase 2 addition."
CustomFilterMap = Mapping[str, Type[Filter]]


def build_filters_from_config(
    config: UseCaseConfig,
    custom_filters: Optional[CustomFilterMap] = None,
) -> dict[str, Filter]:
    """Instantiate one `Filter` per field declared under `config.filters`,
    keyed by field name.

    Parameters
    ----------
    config:
        A validated `UseCaseConfig` (see module docstring).
    custom_filters:
        Optional `{field_name: FilterSubclass}` override map (§6). For
        each declared field, this is checked FIRST: if the field name is
        a key here, that class is instantiated instead of whatever the
        generic registry would have returned for the field's configured
        `operation`. A field name not present in `custom_filters` (or
        `custom_filters=None`, the default) falls back to the generic
        registry exactly as in Phase 1 -- overriding is strictly
        opt-in, per field, never a project-wide behavior change.

    By the time a `UseCaseConfig` exists, its own validation has already
    guaranteed every field's (type, operation) pair is compatible and
    every LIST field has an item_type set correctly -- so `Filter`'s own
    construction-time checks (`app/core/filtering/base.py`) are not
    expected to fail here. They still run regardless (nothing bypasses
    them, override or not); if one somehow does fail, it's re-raised as
    `ConfigLoadError` rather than a bare `FilterError`, so a caller of
    this function gets ONE consistent error type for "this config could
    not be turned into working filters", no matter which layer actually
    caught the problem.

    Raises
    ------
    ConfigLoadError
        If a declared field's operation isn't registered generically and
        has no override; if a `custom_filters` entry's own `operation`
        doesn't match what the field is configured as; or if
        construction fails `Filter.__init__`'s own compatibility checks.
    """
    resolved_overrides: CustomFilterMap = custom_filters or {}

    unknown_override_fields = set(resolved_overrides) - set(config.filters)
    if unknown_override_fields:
        raise ConfigLoadError(
            "custom_filters names field(s) not declared under 'filters' in "
            f"this config: {sorted(unknown_override_fields)} (declared fields: "
            f"{sorted(config.filters)})"
        )

    filters: dict[str, Filter] = {}
    for name, field_cfg in config.filters.items():
        override_cls = resolved_overrides.get(name)
        try:
            if override_cls is not None:
                declared_operation = getattr(override_cls, "operation", None)
                if declared_operation != field_cfg.operation:
                    raise FilterError(
                        f"custom_filters['{name}'] = {override_cls.__name__} declares "
                        f"operation {declared_operation!r}, but filters['{name}'].operation "
                        f"in config is '{field_cfg.operation}' -- an override must implement "
                        "the SAME operation the config declares for that field (a use case "
                        "can override HOW an operation behaves, not silently swap WHICH "
                        "operation a field exposes)."
                    )
                filter_cls = override_cls
            else:
                filter_cls = get_filter_class(field_cfg.operation)

            filters[name] = filter_cls(field_type=field_cfg.type, item_type=field_cfg.item_type)
        except FilterError as exc:
            raise ConfigLoadError(
                f"filters['{name}']: could not build a filter for operation "
                f"'{field_cfg.operation}' on type '{field_cfg.type.value}'"
                f"{' (custom override)' if override_cls is not None else ''}: {exc}"
            ) from exc
    return filters


def load_filters(
    path: Union[str, Path],
    custom_filters: Optional[CustomFilterMap] = None,
) -> tuple[UseCaseConfig, dict[str, Filter]]:
    """Convenience entry point for a project's startup code: load
    config.yaml, validate it, and build every declared filter -- generic
    or custom-overridden (§6, see `build_filters_from_config`) -- in one
    call.

    Raises `ConfigLoadError` for any problem at any stage -- file not
    found, invalid YAML syntax, schema validation (including an
    incompatible type/operation pairing), or filter construction (built
    in or overridden) -- always with a message naming the specific
    field/problem, never a bare stack trace.
    """
    config = load_use_case_config(path)
    filters = build_filters_from_config(config, custom_filters=custom_filters)
    return config, filters