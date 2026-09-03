"""
app/custom/books/fuzzy_title_filter.py

Phase 3, item 2: "one real example custom filter -- fuzzy title
matching -- as the reference implementation of 'how to build a custom
filter correctly.'"

This is the SOURCE DOC'S OWN EXAMPLE, verbatim (§4, "Generic versus
custom filters"): searching a database of books where the user doesn't
know the exact title -- they search for something close to

    Al-Tabaqat al-Kubra

but the actual title stored may differ slightly in spelling or
transliteration (see raw_loader.py: this project's sample catalog
stores it as "Kitab al-Tabaqat al-Kabir"). §4 is explicit that this
belongs in the BOOK application's custom layer, and §11's architecture
diagram confirms it: `Book Search -> Fuzzy title`, while `Legal Search`
is shown with only generic, unspecified "Custom filters". An earlier
version of this file lived under app/custom/legal/ instead, motivated by
a plausible-but-invented "OCR'd legal titles" scenario rather than the
source doc's actual example -- moved here to match §4/§11 once the
source doc itself was available to check against.

Why this is a REAL custom filter, not a toy example
-----------------------------------------------------
`app/custom/books/config.yaml` declares:

    title:
      type: string
      operation: contains

The generic `ContainsFilter` (app/core/filtering/filters.py) does exact,
case-insensitive substring search. That's not enough here: a
transliterated title has no single "correct" spelling -- "al-Tabaqat"
vs. "al-Tabakat" vs. "al-Ṭabaqāt", "al-Kubra" vs. "al-Kabir" (variants
carrying the same meaning, "the great/major [book]") are all reasonable
renderings a user might type, and exact substring search would silently
return nothing for whichever spelling isn't the one stored in the
catalog. `FuzzyTitleContainsFilter` tolerates that variance instead of
requiring a byte-perfect match.

This is also the concrete worked example for `docs/custom-vs-generic.md`'s rule of thumb,
directly from §4's own words: "If we later realize that fuzzy matching
is useful across many applications, we can promote it into the generic
core." This filter starts out books-specific *on purpose* -- if a second
project independently needs approximate text matching (a plausible
future candidate: OCR'd/re-typed titles in another catalog), THAT
repetition is the signal to promote a generalized version into
`app/core/filtering/filters.py`, not to have each project reinvent it.

How to build a custom filter correctly -- the lessons this file models
------------------------------------------------------------------------
1. Depend ONLY on the public surface of `app.core` -- `Filter`,
   `FilterError`, `MetadataFieldType` -- never on private helpers like
   `app.core.filtering.base._as_list` or `_coerce_param_value`, even
   though they'd save a few lines here. Custom code coupling itself to
   core internals is exactly the kind of drift the "repo copy" model
   can't detect until it silently breaks after a core refactor. This
   file re-implements the tiny bit of param-normalization it needs, on
   purpose.
2. Declare `operation = "contains"` -- matching EXACTLY what
   `config.yaml` declares for the `title` field (see
   `app/core/filtering/config_loader.py`'s override-matching check).
   Fuzzy matching is a different *implementation* of "contains", not a
   different *operation*.
3. Follow the same conventions every generic filter follows
   (docs/filtering.md §2): empty/None params is a no-op, a missing
   field value never matches, never mutate the input list, raise
   `FilterError` (not a bare exception) for genuinely malformed
   construction arguments.
4. Keep `Filter.__init__`'s field_type/operation compatibility check as
   a real safety net, and add a narrower one where this class needs one:
   generic "contains" also permits LIST fields, which fuzzy title
   matching over individual list items isn't implemented for here --
   `__init__` rejects that explicitly rather than behaving
   unpredictably.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from typing import Any, Optional, Sequence

from app.core.filtering import Filter, FilterError
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument


def _normalize(value: str) -> str:
    """Case-fold and strip diacritics/accents, so 'al-Ṭabaqāt' and
    'al-tabaqat'/'AL-TABAQAT' all compare equal -- exactly the kind of
    difference transliteration variants introduce."""
    decomposed = unicodedata.normalize("NFD", value)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return without_accents.casefold()


class FuzzyTitleContainsFilter(Filter):
    """Approximate substring matching for a STRING field: matches a
    record if any window of its (normalized) field value is similar
    enough to the (normalized) query, per `difflib.SequenceMatcher`'s
    similarity ratio, rather than requiring an exact substring.

    `threshold` (0.0, 1.0]: the minimum similarity ratio to count as a
    match. 1.0 would only ever match exact substrings; this filter's
    default, 0.82, was chosen empirically as "tolerates a handful of
    spelling/transliteration differences in a mid-length phrase without
    matching unrelated titles" -- tune it per project if needed by
    subclassing with a different default (`CustomFilterMap` only threads
    field_type/item_type through construction, see
    app/core/filtering/config_loader.py, so config.yaml itself can't
    parameterize this in v0).

    Known limitation, stated plainly: the sliding-window scan below is
    O(len(haystack) * len(needle)) per candidate value, which is fine
    for a title field on a corpus of the size this project currently
    handles, but is NOT the implementation to reach for on a much larger
    corpus or a much longer text field without first checking it's still
    fast enough -- this is a correctness-first reference implementation,
    not a performance-tuned one.
    """

    operation = "contains"

    def __init__(
        self,
        field_type: MetadataFieldType,
        item_type: Optional[MetadataFieldType] = None,
        *,
        threshold: float = 0.82,
    ):
        super().__init__(field_type, item_type)
        if field_type != MetadataFieldType.STRING:
            raise FilterError(
                f"FuzzyTitleContainsFilter only supports field_type STRING, "
                f"got '{field_type.value}' -- fuzzy matching over LIST items "
                "isn't implemented here (see module docstring's scope note)."
            )
        if not (0.0 < threshold <= 1.0):
            raise FilterError(f"threshold must be in (0.0, 1.0], got {threshold!r}")
        self.threshold = threshold

    def _best_ratio(self, haystack_norm: str, needle_norm: str) -> float:
        """Highest similarity ratio between `needle_norm` and any
        same-length window of `haystack_norm`. A trivial exact substring
        match (ratio 1.0 window) is always found by this scan, so this
        filter is a strict superset of exact substring matching."""
        window_len = len(needle_norm)
        if window_len == 0:
            return 0.0
        if window_len >= len(haystack_norm):
            return SequenceMatcher(None, needle_norm, haystack_norm).ratio()

        matcher = SequenceMatcher(None, needle_norm, haystack_norm[:window_len])
        best = matcher.ratio()
        for start in range(1, len(haystack_norm) - window_len + 1):
            window = haystack_norm[start : start + window_len]
            matcher.set_seq2(window)
            ratio = matcher.ratio()
            if ratio > best:
                best = ratio
        return best

    def apply(
        self, records: Sequence[NormalizedDocument], field: str, params: Any
    ) -> list[NormalizedDocument]:
        if params is None:
            return list(records)
        values = params if isinstance(params, (list, tuple, set)) else [params]
        needles = [_normalize(str(v)) for v in values if str(v)]
        if not needles:
            return list(records)

        matched: list[NormalizedDocument] = []
        for record in records:
            value = record.metadata.get(field)
            if value is None:
                continue
            haystack_norm = _normalize(str(value))
            if any(self._best_ratio(haystack_norm, needle) >= self.threshold for needle in needles):
                matched.append(record)
        return matched