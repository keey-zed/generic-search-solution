# Pagination

Pagination on the merged, ranked result set, living under
`app/core/search/pagination/`.

Run tests from the repo root with `app/` importable, same as the rest of
the project:

```bash
PYTHONPATH=. python3 -m pytest tests/test_pagination.py
```

## 1. Files

| File | Role |
|---|---|
| `engine.py` | `SearchResultPage` (the response-wrapper model) and `paginate()`, the public entry point. |

## 2. Where this sits in the pipeline

```
Documents -> Retrieval -> List[SearchHit] -> Ranking -> Pagination -> API
                                                          ^^^^^^^^^^
                                                          this module
```

`SearchHit`'s own module docstring is explicit about the boundary this
module respects: *"Page number, page size, and offset are properties of
a request, not of an individual result... If a future need arises to
expose a hit's position, it lives in a page/response wrapper model,
never on SearchHit itself."* `SearchResultPage` is exactly that wrapper
— `SearchHit` gains no new fields for pagination to work.

`paginate()` does **no ranking or re-ordering** of its own. It assumes
`hits` already arrives in final display order — typically straight out
of `app/core/search/ranking/engine.py::merge_and_rank()` — and only ever
slices it. This keeps retrieval → ranking → pagination strictly
one-directional: pagination never needs to know how the list got
ordered, and ranking never needs to know how big a page is.

## 3. `paginate()`

```python
def paginate(
    hits: Sequence[SearchHit],
    *,
    page: int = 1,
    page_size: Optional[int] = None,
    default_page_size: int = 20,
    max_page_size: int = 100,
) -> SearchResultPage: ...
```

- **`page` is 1-indexed** — matching how end users think about "page 1,
  page 2, ..." and how `docs/config-schema.md` describes
  `pagination.default_page_size`/`max_page_size`. `page < 1` raises
  `ValueError` — a malformed request, not something to silently clamp.
- **`page_size` above `max_page_size` is clamped down, not rejected.**
  A client asking for 500 results when the project caps at 100 gets
  100, not an error — this protects the backend from an oversized
  request without penalizing an otherwise reasonable one.
  `page_size <= 0` still raises `ValueError`, same reasoning as `page`.
- **A page beyond the last available page returns an empty `hits` list**
  with `has_next=False`, rather than raising — requesting page 50 of a
  3-page result set is a normal (if uninteresting) outcome.
- `default_page_size` / `max_page_size` are plain `int`s, not
  `PaginationConfig` itself — same reasoning as
  `ranking/engine.py::merge_and_rank`'s `weights` being a plain dict:
  this module has no dependency on `app.core.config`. The API layer is
  expected to pass `config.search.pagination.default_page_size` /
  `.max_page_size` through when wiring this up.

## 4. `SearchResultPage`

| Field | Meaning |
|---|---|
| `hits` | This page's slice of `List[SearchHit]`. |
| `page` | The page actually returned (1-indexed). |
| `page_size` | The page size actually used, after clamping. |
| `total_hits` | Total hits across the whole (unpaginated) result set. |
| `total_pages` | `ceil(total_hits / page_size)`; `0` when `total_hits == 0`. |
| `has_previous` / `has_next` | Whether an adjacent page exists, so a client can render pagination controls without recomputing this itself. |

`hits` is validated to never exceed `page_size` in length — a page
"page" that returns more results than its own declared page size would
indicate a bug in whatever constructed it, not a valid state to pass
through silently.

## 5. What's deliberately NOT built here

- **No cursor-based pagination.** Only page-number-based pagination
  (`page`/`page_size`) is implemented, matching `PaginationConfig`'s
  existing shape in `app/core/config/models.py`
  (`default_page_size`/`max_page_size`, no cursor fields). A project
  needing cursor/keyset pagination for very large result sets would
  need a new config shape and a new function here — not a change to
  `paginate()`'s existing contract.
- **No dependency on `app.core.config`.** Same reasoning as
  `ranking/engine.py` — see §3.
