# Generic Search Factory

A reusable search core (semantic + lexical + generic filtering),
configured per use case via YAML, instead of hand-building a new search
application per document collection. See
`Generic Search Factory – Architecture and Design Principles.md` for
the original design document and the roadmap for how this codebase was
built against it, phase by phase.

## Architecture (source doc §11)

```text
                         ┌───────────────────────┐
                         │     Generic Core      │
                         │                       │
                         │ • Semantic search     │
                         │ • Lexical search      │
                         │ • Boolean logic       │
                         │ • Generic filters     │
                         │ • Ranking             │
                         │ • Pagination          │
                         │ • Common API          │
                         └───────────┬───────────┘
                                     │
                              Configuration
                                  (YAML)
                                     │
                 ┌───────────────────┴───────────────────┐
                 │                                       │
        ┌────────▼────────┐                     ┌────────▼────────┐
        │ Legal Search    │                     │ Book Search     │
        │                 │                     │                 │
        │ Custom config   │                     │ Custom config   │
        │ Custom filters  │                     │ Fuzzy title     │
        │ Branding        │                     │ Branding        │
        └─────────────────┘                     └─────────────────┘
```

Concretely, in this repository:

```text
app/core/       Generic core — never imports a use-case's field names or vocabulary
  schema/         DocumentRecord, typed metadata, Embedding, SearchHit
  ingestion/      raw data + embeddings -> validated, typed documents
  filtering/      Filter interface, EqualityFilter/RangeFilter/ContainsFilter, registry, override chain
  config/         config.yaml parsing, validation, control resolution
  search/         semantic, lexical, ranking, pagination
  embeddings/     embedding model wiring, on-disk cache

app/api/        Common API — SearchEngine, SearchRequest/SearchResultPage, HTTP layer

app/custom/     One folder per project — config.yaml + raw_loader.py + custom_filters.py + bootstrap.py
  _template/      copy this to start a new project
  legal/          worked example of the template mechanism itself
  legal_pilot/    the Phase 4 pilot — full 5-filter set from §4's running example
  books/          the source doc's own §4 fuzzy-title-matching example

tests/          Generic tests (travel with every copy) + project-specific tests (written per project)
docs/           One doc per concern — see the index below
```

## Quick start: use an existing project

```python
from app.custom.legal_pilot.bootstrap import build_search_engine
from app.api.http import create_http_app

engine = build_search_engine()
app = create_http_app(engine)
app.run()
```

## Quick start: build a new project

Follow **`docs/new-project-checklist.md`** — it walks through all seven
of source doc §12's steps concretely, with commands and pointers to the
relevant doc for each one. Read that first if you're new here; the rest
of this README is a reference index, not a tutorial.

## Documentation index

**Start here:**
- `docs/new-project-checklist.md` — the step-by-step guide to standing up a new project.
- `app/custom/_template/README.md` — the custom-layer template's own quick reference.

**Core contracts (Phase 0):**
- `docs/metadata-typing.md` — `DocumentRecord` and typed metadata fields.
- `docs/embeddings-and-search-hit.md` — the `Embedding` abstraction and the generic `SearchHit` shape.

**Data & filtering (Phase 1, Track B):**
- `docs/ingestion.md` — raw data + embeddings → validated, typed documents.
- `docs/filtering.md` — the generic filter framework: range/equality/contains, the registry, the config loader.
- `docs/config-schema.md` — the full `config.yaml` reference, including versioning/migration policy.

**Retrieval (Phase 1, Track A):**
- `docs/semantic-search.md`, `docs/lexical-search.md`, `docs/ranking.md`, `docs/pagination.md`.

**API & override mechanism (Phase 2):**
- `docs/api-layer.md` — the in-process `SearchEngine`/`SearchRequest`/`SearchResultPage` contract.
- `docs/http-layer.md` — the HTTP layer: routes, status codes, CORS.
- `docs/override-mechanism.md` — the §6 generic-default → config → custom-override chain.

**Custom layer (Phase 3):**
- `docs/custom-layer-template.md` — the folder structure and registration pattern.
- `docs/fuzzy-title-filter.md` — the real reference custom filter (books' `title` field).
- `docs/custom-vs-generic.md` — the decision procedure for what belongs where, and the promotion rule.

**Pilot (Phase 4):**
- `docs/pilot-notes.md` — what was (and wasn't) considered a core change while building the pilot.
- `docs/file-backed-ingestion.md` — reading real files off disk for a project's `raw_loader.py`.

**Frontend contract (Phase 5):**
- `docs/frontend-control-mapping.md` — the config→control mapping and the exact payload shape each control must produce.

**Hardening & packaging (Phase 6, this document's own phase):**
- `docs/new-project-checklist.md` — see "Quick start" above.
- `docs/test-suite-baseline.md` — which tests travel with every copy vs. which a project writes for itself.
- `CHANGELOG.md` — the changelog convention for back-porting core improvements across project copies.

## The one rule that matters most

> A new search use case should primarily require configuration, not new
> development.

If building or extending a project means editing anything under
`app/core/` or `app/api/`, stop and read `docs/custom-vs-generic.md`
before proceeding — that file's decision procedure exists specifically
so this doesn't happen by accident.