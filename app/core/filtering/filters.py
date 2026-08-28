"""
app/core/filtering/filters.py

Phase 1, Track B, task 2: the three generic filter kinds from source doc
§3 -- range, equality, contains -- each implementing the shared `Filter`
interface (base.py) and registered under its operation name (registry.py)
so task 3's config loader can instantiate any of them generically.

All three share the same "empty means no-op" convention: a filter given
no params (None, [], or a range with both bounds absent) returns
`records` unchanged rather than matching nothing. This mirrors how a UI
filter control behaves when nothing is selected -- "no doctype chosen"
means "don't restrict by doctype", not "match zero documents" -- and is
exactly the "empty filter list" edge case called out in Track B's
Definition of Done.

All three also share: a record whose field value is missing (None, or an
absent list) never matches a *non-empty* filter. A record can't satisfy
"date between X and Y" if it has no date.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.core.filtering.base import DocT, Filter, FilterError, _as_list, _coerce_param_value
from app.core.filtering.registry import register_filter
from app.core.schema.metadata_types import MetadataFieldType


@register_filter("equality")
class EqualityFilter(Filter):
    """Match records whose field value equals ANY of the given filter
    values (OR semantics across multiple selected values -- e.g. several
    doctypes selected in a dropdown/checkbox-group).

    Works across string/date/int/float/bool, per
    FILTER_OPERATION_COMPATIBILITY (metadata_types.py §5).
    """

    operation = "equality"

    def apply(self, records: Sequence[DocT], field: str, params: Any) -> list[DocT]:
        values = _as_list(params)
        if not values:
            return list(records)

        targets = {_coerce_param_value(v, self.field_type) for v in values}
        return [r for r in records if r.metadata.get(field) in targets]


@register_filter("range")
class RangeFilter(Filter):
    """Match records whose field value falls within [min, max], with
    independently optional bounds and independently configurable
    inclusive/exclusive boundaries per bound.

    Applicable to date/int/float, per FILTER_OPERATION_COMPATIBILITY.

    `params` shape -- a mapping with:
        "min", "max"                          -- bound values (optional, independently)
        "min_inclusive" (default True)
        "max_inclusive" (default True)

    e.g. `{"min": "2020-01-01", "max": "2020-12-31"}` for an inclusive
    calendar-year range, or `{"min": 0, "max": 100, "max_inclusive": False}`
    for `0 <= x < 100`.
    """

    operation = "range"

    def apply(self, records: Sequence[DocT], field: str, params: Any) -> list[DocT]:
        if not params:
            return list(records)

        raw_min = params.get("min")
        raw_max = params.get("max")
        min_inclusive = params.get("min_inclusive", True)
        max_inclusive = params.get("max_inclusive", True)

        if raw_min is None and raw_max is None:
            return list(records)

        min_value = _coerce_param_value(raw_min, self.field_type) if raw_min is not None else None
        max_value = _coerce_param_value(raw_max, self.field_type) if raw_max is not None else None

        if min_value is not None and max_value is not None and min_value > max_value:
            raise FilterError(
                f"range filter on field '{field}': min ({min_value!r}) is greater "
                f"than max ({max_value!r})"
            )

        def in_range(value: Any) -> bool:
            if value is None:
                return False
            if min_value is not None:
                if min_inclusive and value < min_value:
                    return False
                if not min_inclusive and value <= min_value:
                    return False
            if max_value is not None:
                if max_inclusive and value > max_value:
                    return False
                if not max_inclusive and value >= max_value:
                    return False
            return True

        return [r for r in records if in_range(r.metadata.get(field))]


@register_filter("contains")
class ContainsFilter(Filter):
    """Two meanings depending on field_type -- 'contains' is only valid
    for STRING and LIST per FILTER_OPERATION_COMPATIBILITY:

      - STRING: substring search. Case-INSENSITIVE by default (documented
        default: text-search UX generally expects "climate" to match
        "Climate Change Act"). Multiple params -> OR (match if ANY
        substring is found anywhere in the field's text).
      - LIST: membership test -- record's list field contains ANY of the
        given candidate values (OR semantics, e.g. several subjects/tags
        selected). String list items are compared case-insensitively for
        the same reason as substring search; non-string items (int,
        float, bool, date) compare with exact equality, where
        case-sensitivity has no meaning.

    Empty/None params is a no-op (see module docstring).
    """

    operation = "contains"

    def apply(self, records: Sequence[DocT], field: str, params: Any) -> list[DocT]:
        values = _as_list(params)
        if not values:
            return list(records)

        if self.field_type == MetadataFieldType.STRING:
            needles = [str(_coerce_param_value(v, MetadataFieldType.STRING)).lower() for v in values]

            def matches(value: Any) -> bool:
                if value is None:
                    return False
                haystack = str(value).lower()
                return any(needle in haystack for needle in needles)

        elif self.field_type == MetadataFieldType.LIST:
            case_insensitive = self.item_type == MetadataFieldType.STRING
            targets = {_coerce_param_value(v, self.item_type) for v in values}
            if case_insensitive:
                targets = {t.lower() for t in targets}

            def matches(value: Any) -> bool:
                if not value:
                    return False
                if case_insensitive:
                    return any(str(item).lower() in targets for item in value)
                return any(item in targets for item in value)

        else:  # pragma: no cover - unreachable: Filter.__init__ already
            # rejects any field_type not compatible with "contains" via
            # is_operation_compatible(); kept as a defensive guard rather
            # than trusting that check silently forever.
            raise FilterError(
                f"ContainsFilter does not support field_type '{self.field_type.value}' "
                "(only STRING and LIST are valid for the 'contains' operation)"
            )

        return [r for r in records if matches(r.metadata.get(field))]