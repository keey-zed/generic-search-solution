# Custom Layer Template

Copy this folder (`app/custom/_template/`) to `app/custom/<your-project>/`
to start a new project. It's the standard folder structure and
registration pattern every project uses to add project-specific
filters/behavior **without touching `app/core/`** — per the roadmap's
Phase 3, item 1.

See `app/custom/legal/` for a fully filled-in worked example, and
`tests/test_custom_layer_template.py` for the test proving this pattern
actually produces a working `SearchEngine`.

## The four files, in the order you fill them in

| File | You edit it? | What it's for |
|---|---|---|
| `config.yaml` | **Always** | Your fields, their types/operations, search settings, branding. Heavily commented — see the file itself. |
| `raw_loader.py` | **Always** | `load_raw_records()` — turn YOUR raw data format into the standard `{"id", "text", "metadata"}` shape. The only file that needs to know your data's original format. |
| `custom_filters.py` | Only if needed | Register a custom `Filter` for a field where the generic equality/range/contains behavior isn't quite right. Most projects leave this empty. |
| `bootstrap.py` | Rarely | The generic wiring that turns the three files above into a working `SearchEngine`. Copy as-is; you shouldn't normally need to change it. |

## Getting a working `SearchEngine`

```python
from app.custom.<your_project>.bootstrap import build_search_engine

engine = build_search_engine()
result_page = engine.search(some_search_request)
```

That's the entire integration surface — everything else (ingestion,
filtering, search, ranking, pagination) is generic code in `app/core/`
and `app/api/`, already built and tested, that this wiring reuses
unchanged.

## What "without touching core" means in practice

- You never import a legal/book/whatever-specific concept into anything
  under `app/core/`.
- Every field name, type, and operation your project needs is expressed
  in `config.yaml`, not hardcoded anywhere in Python.
- If the generic `EqualityFilter`/`RangeFilter`/`ContainsFilter` can't
  express something your project needs, you write ONE class in
  `custom_filters.py` — you do not edit `app/core/filtering/filters.py`.
- If you ever find yourself editing a file under `app/core/` to make
  your project work, that's a signal worth pausing on: either it's a bug
  in core (fix it generically, benefiting every project), or it's a
  missing generic feature (add it generically, not as a one-off patch).
  This is the promotion rule from the roadmap's §4 — see
  `docs/custom-vs-generic.md` for the concrete decision procedure.

## What this template does NOT include

- **A real custom filter example.** The commented-out example in
  `custom_filters.py` is illustrative only. The actual reference
  implementation (fuzzy title matching) is Phase 3, item 2 — copy that
  one once it exists, rather than the commented placeholder here, if you
  need a real starting point.
- **Embedding computation.** `raw_loader.py` returns text + metadata
  only; if your project uses semantic search, computing embeddings for
  your documents happens separately (whatever embedding model/pipeline
  you use), and you pass the result in via `build_search_engine(embedding_provider=...)`
  or attach embeddings before calling `ingest_raw_records()` yourself if
  you're not using `bootstrap.py` as-is.
- **Deployment/serving.** This template produces a `SearchEngine` object
  you can call `.search()` on in Python. Wrapping it in an HTTP server,
  a CLI, or anything else is outside this template's scope.