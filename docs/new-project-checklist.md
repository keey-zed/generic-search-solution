# New Project Checklist

This document specifies **Phase 6, item 1**: a concrete step-by-step
doc mirroring source doc §12's list, so every future team follows the
same steps in the same order.

**Definition of Done this checklist exists to satisfy**: a developer
unfamiliar with the project can follow it and stand up a second pilot
use case from scratch using only the docs, without pinging either
original developer. If you get stuck on a step below and the doc it
points to doesn't answer your question, that's a documentation bug —
fix the doc, don't just figure it out and move on silently.

§12's seven steps, made concrete against what this codebase actually
provides:

## 1. Prepare the documents in the standard input format

Get your raw data (an XML dump, a CSV export, a database, scraped
pages, whatever) into memory as plain Python dicts shaped like:

```python
{"id": "...", "text": "...", "metadata": {"field_a": ..., "field_b": ...}}
```

This is `load_raw_records()` in your project's `raw_loader.py` (see
step 5) — see `docs/ingestion.md` for the exact contract and
`app/custom/legal/raw_loader.py` / `app/custom/books/raw_loader.py`
for two real, filled-in examples of different shapes.

**Don't** validate types or filter/search anything here — that's every
later step's job, not this one's.

## 2. Prepare or index embeddings (if this project uses semantic search)

Decide how you'll get a vector per document. V1 supports **inline
embeddings**: precomputed `Embedding` objects
(`app/core/schema/embedding.py`) attached to each document at ingestion
time. See `docs/ingestion.md` §3 and `app/embeddings/` for the actual
embedding-model wiring (`app/embeddings/sentence_transformer.py`,
`app/embeddings/cache.py` for avoiding re-embedding unchanged
documents).

If this project has no semantic search need yet, skip this step and
set `search.semantic.enabled: false` in step 4 — lexical-only is a
fully supported configuration (`docs/semantic-search.md` records why
query-time text embedding specifically is a known, deliberate gap, not
an oversight).

## 3. Define the metadata schema

Decide which fields your documents have, their types
(`string`/`date`/`int`/`float`/`bool`/`list`), and which ones need to be
filterable. This becomes the `filters:` block in step 4 directly — there
is no separate "schema" file; `config.yaml` **is** the schema
(`docs/config-schema.md` §2).

## 4. Select the required search and filter capabilities in YAML

Copy `app/custom/_template/config.yaml` to
`app/custom/<your-project>/config.yaml` and fill it in — it's heavily
commented with exactly this step in mind. For each field: `type`,
`operation` (`equality`/`range`/`contains` — pick using
`docs/filtering.md` §3's table), `required`, and optionally a `default`
(`docs/config-schema.md`, "default:" section).

Validate it immediately, before writing any other code:

```bash
PYTHONPATH=. python3 -c "from app.core.config import load_use_case_config; print(load_use_case_config('app/custom/<your-project>/config.yaml'))"
```

A bad `(type, operation)` pairing is rejected here, by name, with what
IS allowed — not discovered later at query time.

## 5. Add genuinely specific operations in the custom layer (only if needed)

Copy the rest of `app/custom/_template/` (`raw_loader.py`,
`custom_filters.py`, `bootstrap.py`, `__init__.py`) alongside your
`config.yaml`. Fill in `raw_loader.py` (step 1). Leave `custom_filters.py`
empty unless a generic filter genuinely can't express something you
need — see `docs/custom-vs-generic.md` for the decision procedure
before writing one. Leave `bootstrap.py` as-is; it's generic wiring, not
project-specific code (see its own docstring for exactly what it does).

**If you find yourself wanting to edit anything under `app/core/` or
`app/api/` to make your project work** — stop. That's either a bug (fix
it generically, it benefits every project) or a missing generic feature
that this checklist's own promotion rule
(`docs/custom-vs-generic.md`) says to add generically, not patch
per-project. Don't proceed past this step with a core edit in hand.

## 6. Define branding and frontend presentation

Fill in your `config.yaml`'s `frontend:` block: `branding` (title,
subtitle, colors, placeholder) and `filters` (which fields get a UI
control, their label/order/placeholder — `docs/config-schema.md` §3).
See `docs/frontend-control-mapping.md` for exactly what each control
renders as and what payload shape it must produce.

## 7. Deploy the application

```python
from app.custom.<your_project>.bootstrap import build_search_engine
from app.api.http import create_http_app

engine = build_search_engine()
app = create_http_app(engine)
app.run()
```

See `docs/http-layer.md` for the full HTTP contract (`/search`,
`/config`, `/facets`, `/documents/<id>`), CORS setup, and how to compose
this into an existing Flask app instead of getting a standalone one.

## Before you consider it done

Run the generic test suite baseline (`docs/test-suite-baseline.md`)
against your project, and write your own pilot-style Definition-of-Done
test proving zero files under `app/core/`/`app/api/` were touched — see
`tests/test_custom_layer_template.py` for the exact pattern to copy.

## Reference: an existing project to read alongside this checklist

`app/custom/legal/` went through every step above for real — its
`config.yaml`, `raw_loader.py`, `custom_filters.py` (empty — no override
was needed), and `bootstrap.py` are a complete, working answer to "what
does 'done' look like."
things that were briefly considered as core changes during that
process and why neither qualified — worth reading before you convince
yourself something needs a core edit.
