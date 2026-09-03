"""
app/custom/_template/custom_filters.py

STEP 3 (OPTIONAL) of adopting this template: register a custom `Filter`
for any field where the generic behavior
(app/core/filtering/filters.py -- EqualityFilter / RangeFilter /
ContainsFilter) isn't quite right for your project.

Most projects need ZERO custom filters -- leave CUSTOM_FILTERS empty and
skip this file entirely. Only add an entry here once you've confirmed
the generic filters genuinely can't do what you need; see
docs/custom-vs-generic.md for the promotion rule (when something should
move from here into app/core/filtering/ instead) and
app/custom/books/fuzzy_title_filter.py /
app/custom/legal/case_insensitive_equality_filter.py for two real,
complete worked examples.

The registration pattern -- this IS the entire mechanism, no decorators,
no global state (see app/core/filtering/config_loader.py's module
docstring, "Phase 2 addition"):

    1. Subclass `Filter` (from app.core.filtering).
    2. Declare `operation = "..."` matching EXACTLY what this field's
       `operation:` is set to in config.yaml. An override changes HOW an
       operation behaves for one field, never WHICH operation that field
       exposes -- a mismatch here is rejected loudly at startup
       (`ConfigLoadError`), not silently ignored.
    3. Implement `apply(self, records, field, params)` -- same contract
       every generic filter follows: return the matching subset of
       `records`, never mutate the input, treat empty/None `params` as
       "no restriction" (see docs/filtering.md §2 for the shared
       conventions every filter -- generic or custom -- should follow).
    4. Add the class to the CUSTOM_FILTERS dict below, keyed by field name.

bootstrap.py passes CUSTOM_FILTERS straight into
`SearchEngine.from_config_path(..., custom_filters=CUSTOM_FILTERS)` --
nothing else in your project needs to change.
"""
from __future__ import annotations

from app.core.filtering import CustomFilterMap, Filter

# ---------------------------------------------------------------------------
# EXAMPLE (commented out): a case-insensitive equality override for a
# field called "category". Uncomment and adapt it, add your own from
# scratch following the same shape, or delete this whole file if you
# don't need any custom filters.
# ---------------------------------------------------------------------------
#
# class CaseInsensitiveCategoryFilter(Filter):
#     operation = "equality"  # MUST match config.yaml's `operation:` for "category"
#
#     def apply(self, records, field, params):
#         if not params:
#             return list(records)  # empty filter = no restriction, per docs/filtering.md
#         values = params if isinstance(params, (list, tuple, set)) else [params]
#         targets = {str(v).casefold() for v in values}
#         return [
#             r for r in records
#             if r.metadata.get(field) is not None
#             and str(r.metadata[field]).casefold() in targets
#         ]
#
# CUSTOM_FILTERS: CustomFilterMap = {"category": CaseInsensitiveCategoryFilter}

CUSTOM_FILTERS: CustomFilterMap = {}