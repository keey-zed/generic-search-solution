"""
app/custom/legal/case_insensitive_equality_filter.py

Phase 3's overall Definition of Done, demonstrated directly: this filter
was written following ONLY `app/custom/_template/README.md` and
`docs/custom-vs-generic.md` -- no core source file beyond the documented
public surface (`Filter`, `FilterError` from `app.core.filtering`;
`MetadataFieldType`/`NormalizedDocument` from
`app.core.schema.metadata_types`) was read to build it. Those are
exactly the imports the template's own `custom_filters.py` comments
already show; nothing here required opening
`app/core/filtering/filters.py`, `base.py`, or `config_loader.py`.

Why this exists (docs/custom-vs-generic.md, "Staying custom" worked
example #1): legal's raw `document_type` values are occasionally typed
with inconsistent case ("Dahir" vs "dahir"), and the generic
`EqualityFilter` is exact-match -- a query for "dahir" would silently
miss a record stored as "Dahir". One project, one field, generic filter
genuinely insufficient: exactly the custom-layer case from
docs/custom-vs-generic.md's decision procedure, step 2.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.core.filtering import Filter
from app.core.schema.metadata_types import NormalizedDocument


class CaseInsensitiveEqualityFilter(Filter):
    """Same as the generic `EqualityFilter`, except string comparison
    ignores case. Declares `operation = "equality"` -- matching exactly
    what config.yaml declares for the field this overrides, per the
    override mechanism's contract (docs/override-mechanism.md): an
    override changes HOW an operation behaves, never WHICH operation a
    field exposes.

    Follows the same conventions every filter in this project follows
    (docs/filtering.md §2, restated in the template's own comments):
    empty/None params is a no-op, a missing field value never matches,
    the input list is never mutated.
    """

    operation = "equality"

    def apply(
        self, records: Sequence[NormalizedDocument], field: str, params: Any
    ) -> list[NormalizedDocument]:
        if params is None:
            return list(records)
        values = params if isinstance(params, (list, tuple, set)) else [params]
        if not values:
            return list(records)
        targets = {str(v).casefold() for v in values}
        return [
            r
            for r in records
            if r.metadata.get(field) is not None and str(r.metadata[field]).casefold() in targets
        ]