"""
app/custom/legal/custom_filters.py

Following app/custom/_template/custom_filters.py's registration pattern.
The legal project currently needs zero custom filters -- the generic
EqualityFilter/RangeFilter/ContainsFilter cover document_type,
publication_date, promulgation_date, subjects, and title (see
config.yaml) correctly as-is.

Left intentionally empty (rather than deleted) to make the pattern
visible: this is what "a project that doesn't need any overrides" looks
like -- not a missing file, an empty registration. (An earlier version
of this file registered a fuzzy title filter here; that was a mistake --
the source doc's own §4/§11 example attributes fuzzy title matching to
the BOOK application specifically, not legal. See
app/custom/books/custom_filters.py and docs/fuzzy-title-filter.md.)
"""
from __future__ import annotations

from app.core.filtering import CustomFilterMap

CUSTOM_FILTERS: CustomFilterMap = {}