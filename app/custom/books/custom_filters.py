"""
app/custom/books/custom_filters.py

Following app/custom/_template/custom_filters.py's registration pattern.

`title` is overridden with `FuzzyTitleContainsFilter`
(fuzzy_title_filter.py, Phase 3 item 2) -- this is the source doc's own
§4/§11 example: approximate title matching, tolerant of the
spelling/transliteration variance a title like "Al-Tabaqat al-Kubra" is
prone to, instead of the generic `ContainsFilter`'s exact substring
search. `author`, `publication_year`, and `subjects` use the generic
filters as-is; nothing about them needed overriding.
"""
from __future__ import annotations

from app.core.filtering import CustomFilterMap
from app.custom.books.fuzzy_title_filter import FuzzyTitleContainsFilter

CUSTOM_FILTERS: CustomFilterMap = {"title": FuzzyTitleContainsFilter}