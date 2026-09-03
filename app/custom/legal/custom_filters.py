"""
app/custom/legal/custom_filters.py

Following app/custom/_template/custom_filters.py's registration pattern.

`document_type` is overridden with `CaseInsensitiveEqualityFilter`
(case_insensitive_equality_filter.py) -- see docs/custom-vs-generic.md's
"Staying custom" worked example for why. Every other declared field
(publication_date, promulgation_date, subjects, title) uses the generic
filters as-is; the generic behavior is already correct for them.
"""
from __future__ import annotations

from app.core.filtering import CustomFilterMap
from app.custom.legal.case_insensitive_equality_filter import CaseInsensitiveEqualityFilter

CUSTOM_FILTERS: CustomFilterMap = {"document_type": CaseInsensitiveEqualityFilter}