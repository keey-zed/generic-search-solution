# Common API Layer & Override Mechanism

The one entry point that turns a
`SearchRequest` into a `SearchResultPage` by running the filtering
framework and the search/ranking/pagination together, the 
override mechanism, and the error/logging baseline every future project
would otherwise reinvent inconsistently.

Read `docs/filtering.md` and `docs/semantic-search.md` /
`docs/lexical-search.md` / `docs/ranking.md` / `docs/pagination.md`

```bash
PYTHONPATH=. python3 -m pytest tests/test_api_orchestrator.py tests/test_override_mechanism.py tests/test_API_definition_of_done.py
```

The API's Definition of Done is verified as one end-to-end acceptance
test in `tests/test_API_definition_of_done.py` — a fake config, a
fake corpus, and fake 2D embeddings run through the whole pipeline, with
one field's generic `equality` filter overridden by a custom stub, and
the result checked for correctness, pagination, and error handling in
one pass. The override seam itself is proven in isolation in
`tests/test_override_mechanism.py`. Everything else is covered in more
depth by `tests/test_api_orchestrator.py`.

## 1. The request shape (`app/api/request.py`)

```python
class SearchRequest(BaseModel):
    semantic: list[SemanticQuery] = []
    lexical: Optional[LexicalQuery] = None
    filters: dict[str, Any] = {}
    page: int = 1
    page_size: Optional[int] = None
```

Source doc §11 describes the common API's input as "semantic
query/queries + boolean rules + filter values + pagination." Each piece
is reused, not reinvented :

| §11 concept          | Field                | Reused from                          |
|-----------------------|----------------------|---------------------------------------|
| semantic query/queries | `semantic`           | `app.core.search.semantic.SemanticQuery` |
| boolean rules          | `lexical`             | `app.core.search.lexical.LexicalQuery`   |
| filter values          | `filters`             | keys are field names from `config.yaml`'s `filters:` block; values are whatever each field's `Filter.apply()` expects |
| pagination             | `page`, `page_size`   | passed straight through to `paginate()` |

Two things are deliberately **not** accepted here:

- **Raw query text.** `semantic` only takes already-computed vectors.
  Turning text into a vector is upstream of the common API, exactly as
  it's upstream of `semantic_search()` itself (see
  `app/core/search/semantic/engine.py`'s module docstring) — an HTTP
  route in front of this API is where "text → embedding model → vector"
  belongs.
- **A request with neither `semantic` nor `lexical`.** `filters` alone
  narrows a candidate set (§3) but is not itself a query (§2) — a
  request that only sets `filters` has nothing to rank on. This is
  enforced at construction time (`SearchRequest`'s own validator), not
  deep inside the orchestrator.

`lexical=None` (skip the lexical stage entirely) is intentionally
different from `lexical=LexicalQuery()` (both `first_of`/`mandatories`
empty — a valid "match everything" rule that **does** run); see
`app/api/orchestrator.py`'s `_run_lexical` docstring.

## 2. The orchestrator (`app/api/orchestrator.py`)

`SearchEngine` bundles one project's `UseCaseConfig`, its built
`Filter`s, its corpus, and (optionally) an `EmbeddingProvider` once at
startup, and exposes one method:

```python
engine = SearchEngine.from_config_path(
    "app/custom/legal/config.yaml",
    documents,                       # Sequence[NormalizedDocument]
    custom_filters={"title": FuzzyTitleFilter},   # optional, §6
    embedding_provider=embedding_provider,        # optional, needed for semantic
)

page: SearchResultPage = engine.search(request)
```

The five stages, always in this order:

```text
SearchRequest
     |
     v
[1] FILTER      Narrows the FULL corpus to a candidate set,
     |          one declared field at a time, AND across fields.
     v
[2] SEARCH      The semantic and/or lexical retrieval run
     |          SCOPED TO the candidate set from [1] — never the whole
     |          corpus. This is the actual integration seam: filtering
     |          decides WHICH documents search is even allowed to
     |          return (§3: "filters narrow the candidate set, search
     |          ranks within it").
     v
[3] RANK        Merges semantic + lexical hits into one
     |          ordered list (`merge_and_rank`).
     v
[4] HYDRATE     Each surviving hit's full metadata is attached from the
     |          source document — retrieval itself never does this (see
     |          `_hydrate_metadata`'s docstring).
     v
[5] PAGINATE    Slices the ranked, hydrated list into one page.
     v
SearchResultPage
```

Each stage is wrapped in `app.api.observability.log_stage` (§3 below)
and every lower-level exception is caught and re-raised as one of two
consistent error types (`app.api.errors`), so nothing calling
`SearchEngine.search()` needs to know about `FilterError`,
`ConfigLoadError`, or a bare `ValueError` from `paginate()` /
`semantic_search()`.

## 3. The §6 override mechanism (`app/core/filtering/config_loader.py`)

Source doc §6: *"generic default → use-case configuration → optional
custom override."* Concretely:

```python
def build_filters_from_config(
    config: UseCaseConfig,
    custom_filters: Optional[Mapping[str, Type[Filter]]] = None,
) -> dict[str, Filter]: ...
```

For each field declared under `config.yaml`'s `filters:` block:

1. **generic default** — look the field's declared `operation` up in
   the global registry (`app/core/filtering/registry.py`).
2. **use-case configuration** — `config.yaml` already decided this
   field's `type` + `operation`; that's what step 1 looks up.
3. **optional custom override** — if `custom_filters` names *this*
   field, that class is instantiated instead of whatever step 1 would
   have picked.

```python
config, filters = load_filters(
    "app/custom/legal/config.yaml",
    custom_filters={"title": FuzzyTitleEqualityFilter},
)
```

An override class must still declare its own `operation: ClassVar[str]`
matching what the field is configured as (an override changes **how**
an operation behaves, never **which** operation a field exposes), and
is still constructed via `Filter.__init__(field_type, item_type)` — so
it still gets the base class's own field_type/operation compatibility
check for free. Both are enforced at load time, raising `ConfigLoadError`
(→ `BadConfigError` when going through `SearchEngine.from_config_path`)
with a message naming the field and the mismatch.

The override map is **per call site, not global**: nothing about it
touches `app/core/filtering/registry.py`, so two different projects
forking this repo can override the same field name completely
differently without any shared state between them.

## 4. Error taxonomy (`app/api/errors.py`)

| Error | Means | Typical cause |
|---|---|---|
| `BadConfigError` | The **project** is misconfigured. | `config.yaml` failed to load/validate; a `custom_filters` override's operation doesn't match its field's declared operation; a semantic request with no `embedding_provider` configured. |
| `BadQueryError` | This **request** is malformed, given an otherwise-valid config. | Unknown filter field name; a filter value the field's type rejects; requesting a search mode `search.yaml` disabled; an invalid `page`/`page_size`; a request with neither `semantic` nor `lexical`. |
| *(no exception)* | **No results.** A well-formed request that legitimately matched nothing. | An empty `SearchResultPage` (`total_hits=0`) is a normal, successful outcome — see `app/api/errors.py`'s module docstring for why this is deliberately not modeled as an error. It is still observable via a dedicated `search.no_results` log event (`app.api.observability.log_no_results`). |

## 5. Structured logging (`app/api/observability.py`)

Each of the four stages (`filtering`, `search`, `ranking`, `pagination`)
logs a `"{stage}.started"` record on entry and a `"{stage}.finished"` (or
`"{stage}.failed"`, on an exception) record on exit, via the
`log_stage()` context manager, under the `"app.api"` logger name.
Structured fields (candidate counts, hit counts, strategy names, ...) go
through `extra=`, never string-formatted into the message, so a project
can attach its own formatter/handler (JSON lines, a log shipper, ...)
without this module changing at all.
