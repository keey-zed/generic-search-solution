# Test Suite Baseline

This document specifies **Phase 6, item 3**: which tests every copied
project should keep, split into what travels with the copy unchanged
versus what a new project writes for itself.

## Two kinds of test in this repo

**Generic (core/API) tests** — depend only on `app/core/` and `app/api/`,
never on any specific project's config, data, or custom filters. These
run unmodified against *any* copy of this repo, because they test the
factory itself, not a particular product of it. If one of these ever
needs project-specific data to pass, that's a sign it accidentally
stopped being generic — see `tests/test_no_domain_vocabulary.py` below.

**Project-specific tests** — depend on `app.custom.<project>`. These are
written once per project and don't travel between copies; they're the
proof that *that* project's config + custom layer produce correct
behavior.

```bash
# Confirm the split yourself at any time:
for f in tests/test_*.py; do grep -l "app\.custom\." "$f" >/dev/null 2>&1 && echo "PROJECT-SPECIFIC: $f" || echo "GENERIC: $f"; done
```

## The generic baseline — keep these, as-is, in every copy

| Test file | What it guards |
|---|---|
| `test_document_schema.py`, `test_metadata_types.py` | The standard `{id, text, metadata}` document contract and type coercion rules (Phase 0). |
| `test_embeddings.py`, `test_search_hit.py` | The embedding abstraction and the generic `SearchHit` retrieval-result shape. |
| `test_ingestion.py`, `test_track_b_definition_of_done.py` | Raw-data → validated/typed document ingestion. |
| `test_filters.py`, `test_filtering_registry.py`, `test_filter_config_loader.py`, `test_filter_field_default.py` | The three generic filter types, the operation registry, and config-driven filter construction. |
| `test_override_mechanism.py` | The §6 override chain (generic default → config → optional custom override) itself — not any specific override. |
| `test_config_schema.py` | `config.yaml` validation: shape, type/operation compatibility, control resolution. |
| `test_semantic_search.py`, `test_lexical_search.py`, `test_Retrieval_definition_of_done.py` | Semantic + lexical retrieval, including the boolean `first_of`/grouped-`mandatories` logic (§2). |
| `test_ranking.py`, `test_pagination.py` | Ranking/merging and pagination, independent of any project's data. |
| `test_api_orchestrator.py`, `test_API_definition_of_done.py` | `SearchEngine`/`SearchRequest`/`SearchResultPage` — the in-process API contract. |
| `test_no_domain_vocabulary.py` | **The one that catches drift directly**: asserts `app/core/` and `app/api/` never reference a specific project's field names or vocabulary. If a new project's work makes this fail, something leaked into core that shouldn't have — see `docs/custom-vs-generic.md`. |
| `test_frontend_control_mapping.py` | The config→control→payload contract documented in `docs/frontend-control-mapping.md` stays in sync with `ControlType`. |

None of these import anything under `app.custom` — copy them verbatim
into a new project's repo copy and they should pass without
modification, using nothing but that copy's own `app/core`/`app/api`.

## What a new project writes for itself

Not copied — written fresh, using the generic baseline's own test files
as the pattern to follow:

1. **Custom filter unit tests**, one file per custom filter registered
   in `custom_filters.py` (if any) — see `tests/test_fuzzy_title_filter.py`
   and `tests/test_case_insensitive_equality_filter.py` for the shape:
   construction/validation, matching behavior including edge cases
   (missing field, empty params, wrong type), and a comparison showing
   what the generic filter would have done differently.
2. **A pilot-style Definition-of-Done smoke test**, proving your project
   runs entirely from `config.yaml` + custom layer with zero files
   touched under `app/core/`/`app/api/`. Copy the pattern from
   `tests/test_pilot_definition_of_done.py`, not its content — that
   file is `legal_pilot`-specific.
3. **A config-mutation test**, if this project exposes the frontend
   contract (`/config`, `/facets`), proving that changing your own
   `config.yaml` alone changes those endpoints' output with zero code
   changes — see `tests/test_phase5_definition_of_done.py`'s pattern
   (YAML-dict mutation via `copy.deepcopy` + `yaml.safe_dump`, not
   fragile string surgery).

## Why this split, not just "run everything"

A generic test failing after a core change is a real regression — fix
core. A project-specific test failing after a core change usually means
either that project's assumption about core's behavior was wrong (worth
understanding before "fixing" anything), or the change was genuinely
breaking (see `docs/config-schema.md`'s versioning policy — does this
warrant a `schema_version` bump?). Keeping the two kinds of test visibly
separate (by directory convention, or just by which imports appear in
each file, as the one-liner above checks) is what makes that triage fast
instead of "run the whole suite and guess."