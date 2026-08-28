"""
app/core/filtering/base.py

Phase 1, Track B, task 2: the shared `Filter` interface every filter type
(built-in or custom, per source doc §4/§6) conforms to.

    apply(records, field, params) -> filtered list of records

Design decisions:

- One Filter INSTANCE is built per declared config field (task 3),
  carrying that field's `field_type` (and `item_type` for LIST fields)
  from construction. `apply()` itself only takes `records`, `field`, and
  `params` -- exactly the interface the source doc specifies -- because
  the field's type is already known to the instance, not re-derived on
  every call.
- Every Filter's `__init__` re-validates field_type/operation
  compatibility using `is_operation_compatible()` /
  `FILTER_OPERATION_COMPATIBILITY` -- the SAME table task 3's config
  loader uses to fail fast at config-load time. This means a Filter
  built directly (e.g. in a test, or by future code that doesn't go
  through the YAML loader) still can't silently be misconfigured
  (`contains` on a `bool` field) -- one compatibility table, checked in
  two places, never two competing definitions of "which operation goes
  with which type".
- `records_or_query` in the source doc's interface sketch is, for v0,
  simply an in-memory `Sequence[NormalizedDocument]` -- there is no query
  builder / DB layer in this project yet. The type is written generically
  (bound to NormalizedDocument, not the ingestion-specific
  IngestedDocument) so filters work unchanged on either shape.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, ClassVar, Optional, Sequence, TypeVar

from app.core.schema.metadata_types import (
    FILTER_OPERATION_COMPATIBILITY,
    MetadataFieldType,
    NormalizedDocument,
    TypedScalar,
    _coerce_scalar,
    is_operation_compatible,
)


class FilterError(Exception):
    """Raised for a problem with how a filter was built or called --
    incompatible field_type/operation pairing, malformed params (wrong
    type, min > max, ...), an unregistered operation name. Never raised
    for "zero records matched", which is a normal, valid result, not an
    error.
    """


DocT = TypeVar("DocT", bound=NormalizedDocument)


class Filter(ABC):
    """Base class every filter type conforms to. Subclasses declare
    `operation: ClassVar[str]` and implement `apply()`."""

    operation: ClassVar[str]

    def __init__(self, field_type: MetadataFieldType, item_type: Optional[MetadataFieldType] = None):
        if not is_operation_compatible(field_type, self.operation):
            allowed = sorted(op for op in FILTER_OPERATION_COMPATIBILITY.get(field_type, set()))
            raise FilterError(
                f"operation '{self.operation}' is not compatible with field_type "
                f"'{field_type.value}' (allowed operations for this type: {allowed})"
            )
        if field_type == MetadataFieldType.LIST and item_type is None:
            raise FilterError(
                f"item_type is required when field_type is LIST (operation '{self.operation}')"
            )
        if field_type != MetadataFieldType.LIST and item_type is not None:
            raise FilterError(
                f"item_type must only be set when field_type is LIST "
                f"(operation '{self.operation}', field_type '{field_type.value}')"
            )
        self.field_type = field_type
        self.item_type = item_type

    @abstractmethod
    def apply(self, records: Sequence[DocT], field: str, params: Any) -> list[DocT]:
        """Return the subset of `records` whose `field` metadata value
        satisfies `params`, under this filter's semantics. Must not
        mutate `records`. Must never raise for "nothing matched" -- an
        empty list is a normal result. Should raise FilterError for
        malformed `params` (wrong type, contradictory bounds, ...)."""
        raise NotImplementedError


def _as_list(params: Any) -> list[Any]:
    """Normalize a filter param that may be a single value or a
    list/tuple/set of values into a plain list. None/missing -> [].
    Used by filters where multiple selected values mean OR semantics
    (e.g. a multi-select of subjects, or several doctypes selected)."""
    if params is None:
        return []
    if isinstance(params, (list, tuple, set)):
        return list(params)
    return [params]


def _coerce_param_value(raw: Any, field_type: MetadataFieldType) -> TypedScalar:
    """Coerce one filter-parameter value to `field_type`, raising
    FilterError on failure.

    Reuses metadata_types._coerce_scalar -- the exact same per-type rules
    ingestion already applies to a record's own metadata values (STRING
    only accepts str, INT/BOOL trap where isinstance(True, int) is True,
    FLOAT upcasts int, DATE requires strict ISO-8601) -- so a filter
    parameter is validated by the SAME rules a record's field value would
    be. This is "type coercion ... done once, centrally": one function,
    reused for both ingestion and filtering, not two separate
    implementations that could drift apart.

    A value that's already the correct native Python type (e.g. a real
    `date` object, rather than an ISO string) is accepted as a fast path
    without going through the string-parsing path at all -- a filter
    called programmatically (not from a JSON request) often already has
    typed values on hand.
    """
    if field_type == MetadataFieldType.DATE and isinstance(raw, date) and not isinstance(raw, bool):
        return raw
    if field_type == MetadataFieldType.STRING and isinstance(raw, str):
        return raw
    if field_type == MetadataFieldType.BOOL and isinstance(raw, bool):
        return raw
    if field_type == MetadataFieldType.INT and isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if field_type == MetadataFieldType.FLOAT and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)

    value, err = _coerce_scalar(raw, field_type, "<filter param>")
    if err is not None:
        raise FilterError(f"invalid filter parameter for type '{field_type.value}': {err}")
    return value