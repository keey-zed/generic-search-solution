# Changelog

This is the changelog for the **core** (`app/core/`, `app/api/`) —
generic, reusable code every project copy shares. It is deliberately
**not** a changelog for any individual project under `app/custom/`;
those don't need one (they're not shared, and don't get back-ported
anywhere).

This file exists to satisfy **Phase 6, item 5**: "so that when a
generic improvement... happens in one project's copy, it's documented
well enough to be manually back-ported to the 'source of truth' template
repo and, from there, to other copies."

## Why this matters more here than in a normal project

Because every future project is a **copy** of this codebase rather than
a shared library/dependency (see the roadmap's Phase 6 framing), a core
improvement made while working on one project doesn't automatically
reach any other project's copy — there's no `pip install --upgrade` step
that does it for you. The only way a good idea (a bug fix, a new generic
filter operation, a promoted custom filter — see
`docs/custom-vs-generic.md`) reaches every copy is if someone:

1. **Writes it here**, in the entry format below, at the time it's made
   — not reconstructed later from memory or a vague commit message.
2. Someone maintaining a different project's copy **reads this file**,
   finds the entries since their last sync, and manually applies the
   relevant ones (usually: `git diff`/cherry-pick the touched files
   under `app/core/`/`app/api/` from the source-of-truth repo, then
   re-run that project's own test suite baseline —
   `docs/test-suite-baseline.md`).

If a change bumps `schema_version`, its entry says so and points to
`docs/config-schema.md`'s migration notes for the exact edits an
existing `config.yaml` needs.

## Entry format

```markdown
## [YYYY-MM-DD] Short title

**Type:** Added | Changed | Fixed | Promoted (custom → generic)
**Touches:** list of `app/core/`/`app/api/` files or modules changed
**schema_version bump:** yes (see docs/config-schema.md) | no

One or two sentences: what changed and why. For a "Promoted" entry,
name which project's custom layer it came from and why it qualified
(docs/custom-vs-generic.md's rule: a second, independent project
needing the same thing) rather than being promoted speculatively.
```

---

## [Unreleased]

Nothing pending back-port at the time this file was first populated.

## History

The entries below reconstruct this repository's actual development
history against the format above, so the convention has real examples
to follow instead of starting from a blank log. Commit hashes refer to
this repository's own git history.

### Phase 0 — Foundational contracts

**Type:** Added
**Touches:** `app/core/schema/` (`document.py`, `metadata_types.py`, `embedding.py`, `search_hit.py`)
**schema_version bump:** n/a (schema_version itself introduced here, as `1`)

The standard `{id, text, metadata}` document shape (`DocumentRecord`),
typed metadata field declarations and coercion rules
(`metadata_types.py`), the inline `Embedding` abstraction
(`EmbeddingProvider`/`InlineEmbeddingProvider`), and the generic
`SearchHit` retrieval-result shape. Everything downstream depends on
these being stable. See `docs/metadata-typing.md`,
`docs/embeddings-and-search-hit.md`.

### Phase 1 — Core capabilities (Track A: retrieval, Track B: data & filtering)

**Type:** Added
**Touches:** `app/core/ingestion/`, `app/core/filtering/`, `app/core/config/`, `app/core/search/` (`semantic/`, `lexical/`, `ranking/`, `pagination/`)

Two parallel tracks: (A) semantic search with multi-query combination,
lexical boolean matching (`first_of`/grouped `mandatories`), ranking,
and pagination; (B) the ingestion/normalization layer, the three generic
filter types (`EqualityFilter`/`RangeFilter`/`ContainsFilter`) behind one
shared interface, the operation registry, and the YAML config loader
that turns `config.yaml` into live `Filter` instances. See
`docs/ingestion.md`, `docs/filtering.md`, `docs/config-schema.md`,
`docs/semantic-search.md`, `docs/lexical-search.md`, `docs/ranking.md`,
`docs/pagination.md`.

### Phase 2 — Common API & override mechanism

**Type:** Added
**Touches:** `app/api/` (new), `app/core/filtering/config_loader.py`

`SearchEngine`/`SearchRequest`/`SearchResultPage` as the in-process API
surface, plus the §6 override chain (generic default → use-case config →
optional custom override) via an explicit `custom_filters` mapping
threaded through `build_filters_from_config()`/`load_filters()` —
deliberately not a global registry, so two projects can override the
same field name independently without colliding. See `docs/api-layer.md`,
`docs/override-mechanism.md`.

### Phase 3 — Custom layer scaffolding & fuzzy-match precedent

**Type:** Added
**Touches:** `app/custom/_template/` (new — not core, but the standard
pattern every project's custom layer follows)

The copy-paste project template (`config.yaml`, `raw_loader.py`,
`custom_filters.py`, `bootstrap.py`), the real fuzzy-title-matching
reference custom filter (source doc §4's own example — attributed to
the *book* application, per §11's diagram), the case-insensitive
`document_type` filter (the literal proof that a third developer can
build a working custom filter from the template + docs alone, no core
source reading required), and `docs/custom-vs-generic.md`'s promotion
decision procedure. See `docs/custom-layer-template.md`,
`docs/fuzzy-title-filter.md`, `docs/custom-vs-generic.md`.

### Phase 4 — First legal project (`app/custom/legal/`)

**Type:** Fixed / Added
**Touches:** none under `app/core/`/`app/api/` — that's the point.

The pilot itself is project-specific, not a core change — see
`docs/custom-vs-generic.md`, which records the two points that were briefly
considered as possible core changes during the pilot (query-time
semantic embedding; an `allowed_values` declaration for dropdown
enums) and why neither qualified. **Zero files under `app/core/` or
`app/api/` were touched to build this pilot** — the strongest evidence
so far that the core is actually generic.

### Phase 5 — Frontend wiring (backend contract half)

**Type:** Added
**Touches:** `app/api/http.py` (`/config`, `/facets`, `/documents/<id>`, `/documents/<id>/source`)

The backend contract a frontend consumes to render config-driven
controls without frontend code changes: resolved branding/filter/control
list (`GET /config`) and live per-field value/range summaries
(`GET /facets`). See `docs/frontend-control-mapping.md` for the full
response shapes and the payload contract each control must produce, and
`tests/test_phase5_definition_of_done.py` for the proof that adding,
removing, reordering, and relabeling a filter in YAML alone changes
these endpoints' output with zero code changes.

### Phase 6 — Hardening & packaging

**Type:** Added (documentation only — no `app/core/`/`app/api/` behavior changed)
**Touches:** `README.md`, `CHANGELOG.md`, `docs/new-project-checklist.md`, `docs/test-suite-baseline.md`, `docs/override-mechanism.md`

This phase. The architecture overview + documentation index (this
repo's previously-empty `README.md`), this changelog convention, the
concrete new-project checklist (mirroring §12), the test-suite baseline
split (generic vs. project-specific), migration-notes format for future
`schema_version` bumps (`docs/config-schema.md`), and the
previously-missing override-mechanism how-to (referenced from several
other docs but never written).
