"""
app/custom/legal_pilot/custom_filters.py

Following app/custom/_template/custom_filters.py's registration pattern.

Deliberately EMPTY. This is the actual result for this project:
all five required filters (document_type, publication_date,
promulgation_date, issuing_authority, legal_status) plus the bonus
`title` contains-filter are fully satisfied by the generic
EqualityFilter/RangeFilter/ContainsFilter (app/core/filtering/filters.py)
as declared in config.yaml. Nothing about this pilot's field set needed
a custom override the way app/custom/legal/'s document_type field did
(case-insensitive matching, see app/custom/legal/custom_filters.py) or
app/custom/books/'s title field did (fuzzy matching).

See docs/pilot-notes.md for the record of what WAS considered
and rejected as a custom-filter candidate during this pilot, and why
none of it justified one.
"""
from __future__ import annotations

from app.core.filtering import CustomFilterMap

CUSTOM_FILTERS: CustomFilterMap = {}
