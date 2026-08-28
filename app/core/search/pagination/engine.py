"""
app/core/search/pagination/engine.py

Slicing an already-ordered `List[SearchHit]` into pages.

    Documents -> Retrieval -> List[SearchHit] -> Ranking -> Pagination -> API
                                                              ^^^^^^^^^^
                                                              this module

Per `SearchHit`'s own module docstring: "Page number, page size, and
offset are properties of a *request*, not of an individual result...
If a future need arises to expose a hit's position, it lives in a
page/response wrapper model, never on SearchHit itself." `SearchResultPage`
below is exactly that wrapper model -- `SearchHit` itself gains no new
fields for pagination to work.

This module does no ranking or re-ordering of its own -- it assumes
`hits` already arrives in final display order (e.g. straight out of
`app/core/search/ranking/engine.py::merge_and_rank()`), and only ever
slices it. This keeps the retrieval -> ranking -> pagination stages
strictly one-directional: pagination never needs to know how `hits` got
ordered, and ranking never needs to know how many results a page holds.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.schema.search_hit import SearchHit


class SearchResultPage(BaseModel):
    """One page of an already-ranked result set, plus enough metadata
    for a client to render pagination controls and fetch adjacent pages.

    `page` is 1-indexed (matching how `pagination.default_page_size` /
    `max_page_size` are described in `docs/config-schema.md`, and how
    end users think about "page 1, page 2, ..." -- 0-indexing pagination
    is an implementation detail this schema doesn't expose).
    """

    model_config = ConfigDict(extra="forbid")

    hits: list[SearchHit]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., gt=0)
    total_hits: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)
    has_previous: bool
    has_next: bool

    @model_validator(mode="after")
    def hits_length_within_page_size(self) -> "SearchResultPage":
        if len(self.hits) > self.page_size:
            raise ValueError(
                f"a page cannot contain more hits ({len(self.hits)}) than its page_size ({self.page_size})"
            )
        return self


def paginate(
    hits: Sequence[SearchHit],
    *,
    page: int = 1,
    page_size: Optional[int] = None,
    default_page_size: int = 20,
    max_page_size: int = 100,
) -> SearchResultPage:
    """Slice `hits` (assumed already in final ranked order) into the
    requested page.

    Parameters
    ----------
    hits:
        The full, already-ranked result set -- typically
        `merge_and_rank()`'s output. Not re-sorted here.
    page:
        1-indexed page number. Must be `>= 1`; raises `ValueError`
        otherwise (an invalid page number is a malformed request, not
        something to silently clamp).
    page_size:
        Requested page size. `None` uses `default_page_size`. A
        requested `page_size` above `max_page_size` is silently CLAMPED
        DOWN to `max_page_size` rather than rejected -- matching typical
        API pagination behavior of protecting the backend from an
        oversized request without erroring on an otherwise reasonable
        one. Must be `> 0` if given; raises `ValueError` otherwise.
    default_page_size, max_page_size:
        Mirror `PaginationConfig.default_page_size` /
        `PaginationConfig.max_page_size` from
        `app/core/config/models.py`. Passed as plain ints (not the
        config model itself) for the same reason
        `ranking/engine.py::merge_and_rank`'s `weights` is a plain dict:
        this module has no dependency on `app.core.config`.

    Returns
    -------
    A `SearchResultPage`. A `page` beyond the last available page
    returns an empty `hits` list with `has_next=False`, rather than
    raising -- requesting page 50 of a 3-page result set is a normal
    (if uninteresting) outcome, not an error.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")

    resolved_page_size = default_page_size if page_size is None else page_size
    if resolved_page_size <= 0:
        raise ValueError(f"page_size must be > 0, got {resolved_page_size}")
    resolved_page_size = min(resolved_page_size, max_page_size)

    total_hits = len(hits)
    total_pages = math.ceil(total_hits / resolved_page_size) if total_hits > 0 else 0

    start = (page - 1) * resolved_page_size
    end = start + resolved_page_size
    page_hits = list(hits[start:end])

    return SearchResultPage(
        hits=page_hits,
        page=page,
        page_size=resolved_page_size,
        total_hits=total_hits,
        total_pages=total_pages,
        has_previous=page > 1,
        has_next=page < total_pages,
    )
