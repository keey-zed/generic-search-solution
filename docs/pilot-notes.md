# Pilot Notes — `app/custom/legal_pilot/`

> Note every point where you were tempted to modify `core/` to make
> this use case work — each one is either a bug (fix it)
> or a sign a generic feature was missed (add it now, generically,
> before proceeding — do **not** patch it in a use-case-specific way
> inside core).

The pilot itself lives at `app/custom/legal_pilot/`: a 12-record
realistic legal corpus with all five filters called for by the source
doc's §4 running example (`document_type`, `publication_date`,
`promulgation_date`, `issuing_authority`, `legal_status`), plus a
bonus `title` contains-filter. See `tests/test_pilot_definition_of_done.py`
for the end-to-end proof, and `scripts/pilot_smoke_test.py` for
a runnable walkthrough.

**Bottom line: zero files under `app/core/` or `app/api/` were added,
removed, or modified to build this pilot.** `custom_filters.py` is
empty (`CUSTOM_FILTERS = {}`) — every one of the five required filters,
and the bonus one, is satisfied by the generic `EqualityFilter` /
`RangeFilter` / `ContainsFilter` exactly as declared in `config.yaml`.

Two points came up during this pilot that were briefly considered as
possible core changes. Neither qualified — recorded here per the
promotion rule in `docs/custom-vs-generic.md`, so a future contributor
doesn't have to re-litigate either one from scratch.

## 1. Semantic queries require a pre-computed vector, not query text

`SemanticQuery` (`app/core/search/semantic/engine.py`) takes a
`vector: list[float]` — there is no "embed this query string for me"
step anywhere in `app/core/`. Exercising the pilot's semantic-search
path (`tests/test_pilot_definition_of_done.py::test_pilot_semantic_search_path_runs_and_hydrates_metadata`)
meant supplying a fake pre-computed vector as the "query embedding"
rather than passing natural-language text.

**Not a gap.** The
roadmap explicitly says: *"decide up front
which of the three [embedding] options... is the default for v1... Do
not implement all three."* Query-time text-to-vector embedding is a
model-serving concern (which embedding model, which API/local
inference path, batching, latency) that's orthogonal to the filtering
and ranking logic actually built, and every project's
`custom_filters.py`/`bootstrap.py`-equivalent is the natural place to
embed a query before constructing a `SemanticQuery`, exactly the same
way a project's `raw_loader.py` is the natural place to embed its
documents before calling `ingest_raw_records()`.

**Resolution:** no core change. If a second pilot independently needs
the same "embed query text at request time" step, that repetition is
the actual promotion signal (per `docs/custom-vs-generic.md`'s
decision procedure) for adding a small, provider-agnostic
`QueryEmbedder` seam to `app/api/` — not something to add speculatively
now off one pilot.

## 2. Equality filters have no `allowed_values` declaration for UI dropdowns

While writing `config.yaml`'s `frontend.filters` section, `document_type`,
`issuing_authority`, and `legal_status` are all configured with
`control: dropdown` (or the default control), but `FilterFieldConfig`
(`app/core/config/models.py`) has no field for declaring the enum of
legal values (`"dahir" | "decret" | "loi" | "arrete"`, etc.) that a
dropdown would need to render its options ahead of a query.

**Considered as a possible addition** to `FilterFieldConfig` (an
optional `allowed_values: list` field, validated the same way `default`
already is). **Not added**, for two reasons:

1. It's a frontend/presentation concern, not a filtering-correctness
   one — the generic `EqualityFilter` already works perfectly without
   it (proven by `test_pilot_document_type_equality_filter` /
   `test_pilot_issuing_authority_equality_filter` /
   `test_pilot_legal_status_equality_filter`, all passing with zero
   core changes). Nothing about *filtering* was blocked.
2. It's solvable today, per-project, without any core change: a
   frontend can derive the distinct values for a dropdown by querying
   the ingested corpus directly (`{doc.metadata[field] for doc in
   documents}`), which is arguably more correct than a hand-maintained
   config list anyway (it can't drift out of sync with the real data).

**Resolution:** no core change, and no custom-layer workaround needed
either — this pilot's `frontend.filters` entries for the three dropdown
fields are declared without an enum, exactly as `FrontendFilterOverride`
already allows. Worth revisiting only if a real frontend
implementation finds deriving options from data insufficient
in practice (e.g. wanting to show an option that has zero matching
documents yet) — at that point it's a concrete, evidenced feature
request rather than a guess.

## What this pilot does NOT demonstrate

Per `docs/custom-vs-generic.md`'s "default to custom" principle, this
pilot deliberately did not manufacture a custom filter to prove the
override mechanism works — that's already proven by `app/custom/legal/`
(`CaseInsensitiveEqualityFilter`) and `app/custom/books/`
(fuzzy title matching). This pilot's job was specifically to
prove the *generic* filters are sufficient for a full, realistic field
set — and an empty `CUSTOM_FILTERS` is the correct, honest result of
that check, not a gap in coverage.

## Definition of Done — sign-off

> "pilot app runs fully from config + custom layer with zero
> use-case-specific code in `core/`."

- [x] Config (`app/custom/legal_pilot/config.yaml`) loads and validates
      against the real `UseCaseConfig` schema.
- [x] Ingestion (`ingest_raw_records`) reports 12/12 valid records, 0
      errors, 0 duplicates.
- [x] All five required filters (`document_type`, `publication_date`,
      `promulgation_date`, `issuing_authority`, `legal_status`) verified
      individually and in combination, via the real `SearchEngine`.
- [x] Lexical search, semantic search, ranking, and pagination all
      exercised end to end through the unmodified orchestrator.
- [x] `custom_filters.py` is empty — no custom filter was needed.
- [x] `git status` confirms zero files touched under `app/core/` or
      `app/api/`.
- [x] Full existing test suite (538 tests) still passes unmodified,
      plus 13 new tests for this pilot (`tests/test_pilot_definition_of_done.py`)
      — 551 total, 0 failures.

The core is validated as reusable for a second,
independent, full-field-set legal use case without modification —
proceed to frontend wiring using this pilot as the
config/data contract to render against.
