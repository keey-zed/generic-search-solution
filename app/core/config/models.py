"""
app/core/config/models.py

Phase 0, Deliverable 4: the YAML config schema (v0) every project's
`config.yaml` must conform to, with four required top-level keys:

    schema_version   int, must be a version this core supports
    filters:         backend field declarations (type, operation, required)
    search:          generic search/ranking/pagination behavior
    frontend:        presentation layer (branding + per-filter UI overrides)

Design principle carried over from Phase 0's metadata typing layer: this
schema does NOT redeclare field typing rules. `filters.<name>.type` and
`.item_type` reuse the exact same `MetadataFieldType` enum from
core/schema/metadata_types.py, and `FilterFieldConfig` validates its
operation against the SAME `FILTER_OPERATION_COMPATIBILITY` matrix used
by ingestion. This is deliberate: source-doc §5 explicitly calls out
avoiding "duplicating the same configuration logic in several places" —
a config that declares a `contains` filter on a `bool` field must be
rejected by the exact same rule everywhere, not by two independently
maintained copies of that rule that could quietly drift apart.

`UseCaseConfig.to_metadata_schema()` converts the validated `filters:`
block directly into the `MetadataSchema` (`list[MetadataFieldDef]`) that
ingestion's `normalize_metadata()` / `validate_document_batch()` expect —
closing the loop between config and ingestion typing with a single
source of truth.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.schema.metadata_types import (
    FILTER_OPERATION_COMPATIBILITY,
    MetadataFieldDef,
    MetadataFieldType,
    MetadataSchema,
    is_operation_compatible,
)

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

# Bump when a BREAKING change is made to this schema (a change that would
# make an existing valid config.yaml invalid, or silently change its
# meaning). Additive, backward-compatible changes (a new optional field
# with a safe default) do not require a version bump. See
# docs/config-schema.md, "Versioning policy."
SUPPORTED_SCHEMA_VERSIONS: set[int] = {1}

_FIELD_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------------------
# filters:
# ---------------------------------------------------------------------------

FilterOperation = Literal["equality", "range", "contains"]


class FilterFieldConfig(BaseModel):
    """One entry under `filters:` — the backend truth for one metadata
    field: its type, whether it's required at ingestion, and which
    generic filter operation (source doc §3) it exposes."""

    model_config = ConfigDict(extra="forbid")

    type: MetadataFieldType
    item_type: Optional[MetadataFieldType] = None
    required: bool = False
    operation: FilterOperation

    @model_validator(mode="after")
    def validate_shape_and_operation(self) -> "FilterFieldConfig":
        # Mirrors MetadataFieldDef's own item_type rule (core/schema/metadata_types.py).
        # Kept as a small, self-contained check here (rather than delegating to
        # MetadataFieldDef, which requires a `name` this model doesn't have) —
        # a dedicated cross-check test in tests/test_config_schema.py verifies
        # the two rule sets never diverge.
        if self.type == MetadataFieldType.LIST:
            if self.item_type is None:
                raise ValueError("item_type is required when type == 'list'")
            if self.item_type == MetadataFieldType.LIST:
                raise ValueError("item_type must be a scalar type (nested lists are not supported)")
        elif self.item_type is not None:
            raise ValueError("item_type must only be set when type == 'list'")

        if not is_operation_compatible(self.type, self.operation):
            allowed = sorted(FILTER_OPERATION_COMPATIBILITY.get(self.type, set()))
            raise ValueError(
                f"operation '{self.operation}' is not compatible with type '{self.type.value}' "
                f"(allowed operations for this type: {allowed})"
            )
        return self


# ---------------------------------------------------------------------------
# frontend: — control-type compatibility (parallel to FILTER_OPERATION_COMPATIBILITY)
# ---------------------------------------------------------------------------

ControlType = Literal[
    "text", "dropdown", "radio",
    "date", "date_range",
    "number", "number_range",
    "checkbox", "toggle",
    "multi_select", "checkbox_group",
]

# Every (type, operation) pair that FILTER_OPERATION_COMPATIBILITY allows
# must have exactly one entry here — enforced by
# test_every_compatible_type_operation_pair_has_a_default_control.
DEFAULT_CONTROL: dict[tuple[MetadataFieldType, str], ControlType] = {
    (MetadataFieldType.STRING, "equality"): "dropdown",
    (MetadataFieldType.STRING, "contains"): "text",
    (MetadataFieldType.DATE, "equality"): "date",
    (MetadataFieldType.DATE, "range"): "date_range",
    (MetadataFieldType.INT, "equality"): "number",
    (MetadataFieldType.INT, "range"): "number_range",
    (MetadataFieldType.FLOAT, "equality"): "number",
    (MetadataFieldType.FLOAT, "range"): "number_range",
    (MetadataFieldType.BOOL, "equality"): "checkbox",
    (MetadataFieldType.LIST, "contains"): "multi_select",
}

ALLOWED_CONTROLS: dict[tuple[MetadataFieldType, str], set[str]] = {
    (MetadataFieldType.STRING, "equality"): {"dropdown", "radio"},
    (MetadataFieldType.STRING, "contains"): {"text"},
    (MetadataFieldType.DATE, "equality"): {"date"},
    (MetadataFieldType.DATE, "range"): {"date_range"},
    (MetadataFieldType.INT, "equality"): {"number", "dropdown"},
    (MetadataFieldType.INT, "range"): {"number_range"},
    (MetadataFieldType.FLOAT, "equality"): {"number"},
    (MetadataFieldType.FLOAT, "range"): {"number_range"},
    (MetadataFieldType.BOOL, "equality"): {"checkbox", "toggle"},
    (MetadataFieldType.LIST, "contains"): {"multi_select", "checkbox_group"},
}


class FrontendFilterOverride(BaseModel):
    """UI presentation for one filter, referencing a name declared under
    the top-level `filters:` block. Deliberately holds NO type/operation
    of its own — that would be a second copy of backend truth. If the
    field isn't listed under `filters:`, this entry is invalid."""

    model_config = ConfigDict(extra="forbid")

    label: str
    control: Optional[ControlType] = None  # None -> resolved to a default in UseCaseConfig
    order: int
    placeholder: Optional[str] = None

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must not be blank")
        return v


class BrandingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    subtitle: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    search_placeholder: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v

    @field_validator("primary_color")
    @classmethod
    def valid_hex_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError("primary_color must be a 6-digit hex color, e.g. '#1A2B3C'")
        return v


class FrontendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branding: BrandingConfig
    # Only fields listed here get a rendered UI control. A field present
    # under `filters:` but absent here remains filterable via the API but
    # is NOT shown in the UI. This is a deliberate opt-in default: a
    # developer forgetting to add a frontend entry for a new backend
    # filter fails safe (filter stays hidden) rather than failing open
    # (an internal/unfinished filter accidentally appears in the UI).
    filters: dict[str, FrontendFilterOverride] = Field(default_factory=dict)
    # Field names shown on result cards. NOT cross-validated against
    # `filters:` (a displayed field need not be filterable) — see
    # docs/config-schema.md "Deferred" for why this stays unvalidated in v0.
    result_card_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# search:
# ---------------------------------------------------------------------------


class SemanticSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # How multiple simultaneous semantic queries (source doc §2) are
    # combined into one ranked set. Exactly two strategies exist in v0 —
    # extend deliberately (see docs/config-schema.md).
    multi_query_combination: Literal["max_score", "weighted_average"] = "max_score"


class LexicalSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class RankingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic: float = Field(default=0.5, ge=0)
    lexical: float = Field(default=0.5, ge=0)


class RankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Literal with one value today — when a second strategy is added,
    # revisit whether `weights` should become conditionally
    # required/forbidden per strategy (not needed while there's only one).
    strategy: Literal["weighted_sum"] = "weighted_sum"
    weights: RankingWeights = Field(default_factory=RankingWeights)

    @model_validator(mode="after")
    def weights_not_both_zero(self) -> "RankingConfig":
        if self.weights.semantic == 0 and self.weights.lexical == 0:
            raise ValueError("ranking.weights: semantic and lexical cannot both be 0 (ranking would be a no-op)")
        return self


class PaginationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_page_size: int = Field(default=20, gt=0)
    max_page_size: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def default_not_greater_than_max(self) -> "PaginationConfig":
        if self.default_page_size > self.max_page_size:
            raise ValueError(
                f"default_page_size ({self.default_page_size}) cannot exceed "
                f"max_page_size ({self.max_page_size})"
            )
        return self


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic: SemanticSearchConfig = Field(default_factory=SemanticSearchConfig)
    lexical: LexicalSearchConfig = Field(default_factory=LexicalSearchConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)

    @model_validator(mode="after")
    def at_least_one_mode_enabled(self) -> "SearchConfig":
        if not self.semantic.enabled and not self.lexical.enabled:
            raise ValueError(
                "at least one of search.semantic.enabled or search.lexical.enabled must be true "
                "(a search engine with both disabled can never return results)"
            )
        return self


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class UseCaseConfig(BaseModel):
    """The full, validated contents of one project's config.yaml."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    filters: dict[str, FilterFieldConfig] = Field(default_factory=dict)
    search: SearchConfig
    frontend: FrontendConfig

    @field_validator("schema_version")
    @classmethod
    def supported_version(cls, v: int) -> int:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"schema_version {v} is not supported by this core "
                f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
            )
        return v

    @field_validator("filters")
    @classmethod
    def valid_field_names(cls, v: dict[str, FilterFieldConfig]) -> dict[str, FilterFieldConfig]:
        for name in v:
            if not _FIELD_NAME_PATTERN.fullmatch(name):
                raise ValueError(
                    f"filter field name '{name}' is invalid — use only letters, digits, "
                    "and underscores, starting with a letter or underscore"
                )
        return v

    @model_validator(mode="after")
    def cross_validate_frontend_against_filters(self) -> "UseCaseConfig":
        problems: list[str] = []
        known_fields = set(self.filters.keys())

        for name, override in self.frontend.filters.items():
            if name not in known_fields:
                problems.append(
                    f"frontend.filters['{name}']: no matching entry under 'filters' "
                    f"(declared filter names: {sorted(known_fields)})"
                )
                continue

            field_cfg = self.filters[name]
            key = (field_cfg.type, field_cfg.operation)

            if override.control is None:
                # Resolve and fill in the default now, so every consumer
                # downstream (frontend renderer) always sees a concrete,
                # valid control — never has to know the default-resolution
                # rule itself.
                override.control = DEFAULT_CONTROL[key]
            elif override.control not in ALLOWED_CONTROLS.get(key, set()):
                allowed = sorted(ALLOWED_CONTROLS.get(key, set()))
                problems.append(
                    f"frontend.filters['{name}'].control = '{override.control}' is not valid "
                    f"for type '{field_cfg.type.value}' + operation '{field_cfg.operation}' "
                    f"(allowed: {allowed})"
                )

        orders = [ov.order for ov in self.frontend.filters.values()]
        duplicate_orders = sorted({o for o in orders if orders.count(o) > 1})
        if duplicate_orders:
            problems.append(
                f"frontend.filters: duplicate 'order' values found: {duplicate_orders} "
                "— each exposed filter's order must be unique"
            )

        if problems:
            raise ValueError("; ".join(problems))
        return self

    def to_metadata_schema(self) -> MetadataSchema:
        """Convert `filters:` into the MetadataSchema ingestion expects
        (core/schema/metadata_types.py). This is THE integration point
        between config and ingestion — call this once at startup and
        pass the result to `normalize_metadata` / `validate_document_batch`,
        rather than hand-writing a second field list anywhere."""
        return [
            MetadataFieldDef(
                name=name,
                type=f.type,
                item_type=f.item_type,
                required=f.required,
            )
            for name, f in self.filters.items()
        ]
