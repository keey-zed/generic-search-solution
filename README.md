# Generic Search Factory

A reusable search core — semantic search, lexical/boolean search, generic
filtering, ranking, and pagination — that is configured per use case
through YAML rather than rebuilt per project. See the source design docs
for the full rationale:

- *Generic Search Factory – Architecture and Design Principles* (the "why")
- *Generic Search Factory — Implementation Roadmap* (the "how", phase by phase)

## Status

Phases 0-4 of the roadmap are complete and enforced by the test suite:

| Phase | What | Where |
|---|---|---|
| 0 | Frozen contracts (document schema, embeddings interface, search-hit schema, YAML config schema v0) | `app/core/schema/`, `app/core/config/` |
| 1 | Generic core: semantic search, lexical/boolean search, ranking, pagination, ingestion, generic filters, config loader, filter registry | `app/core/search/`, `app/core/ingestion/`, `app/core/filtering/` |
| 2 | Common API/orchestrator + override mechanism + error handling/observability + HTTP transport | `app/api/` (see `docs/http-layer.md`) |
| 3 | Custom-layer template + fuzzy-title reference implementation | `app/custom/_template/`, `app/custom/books/` |
| 4 | Reference pilot (legal use case) built entirely through config + custom layer, zero `core/` edits | `app/custom/legal_pilot/`, `docs/pilot-notes.md` |

Phase 5 (frontend wiring to the same YAML config contract) has not started -
this repo is backend-only so far. Phase 6 (hardening/packaging for
repo-copy-per-project) is partially done; see `docs/` for what exists.

Run the test suite:

```bash
pip install -e ".[dev,fuzzy,http]"
pytest
```

Note on scope: only phases 0-4 are targeted as "done" right now. Phases
5-7 (frontend wiring, hardening/packaging for repo-copy handoff, and
rollout to further use cases) are deliberately out of scope for this
pass and untouched.

## Layout

```
app/
  core/       # generic, use-case-agnostic. Must never reference a domain
              # field name ("publication_date", "document_type", ...).
              # Enforced by tests/test_no_domain_vocabulary.py.
  api/        # the common orchestrator (Phase 2) that wires filtering +
              # search + ranking + pagination into one request/response.
  custom/     # one directory per use case (legal, books, legal_pilot),
              # plus custom/_template/ as the starting point for a new one.
  data_loader.py, semantic_engine.py, services.py, routes.py, run.py
              # the PREVIOUS, hand-built ("artisan") search app this
              # factory is meant to replace. Kept for reference only -
              # not imported by app/core, app/api, or app/custom, and not
              # a dependency of the generic core (see pyproject.toml's
              # `legacy-app` extra). Do not build new use cases here.
docs/         # design/reference docs for each core subsystem
tests/        # unit tests + one Definition-of-Done test file per phase
scripts/      # demo_API.py, demo_Retrieval.py, pilot_smoke_test.py
```

## Adding a new use case

Not yet formalized as a numbered checklist doc for a repo-copy handoff.
Until that exists, follow `app/custom/legal_pilot/` as the worked example:
`config.yaml` + `raw_loader.py` + `bootstrap.py`, with `custom_filters.py`
only if a generic `Filter` genuinely isn't enough (see
`docs/custom-vs-generic.md` for the promotion rule).
