# Standard Document Schema & Metadata Typing

This document specifies **Phase 0, Deliverable 1** of the roadmap: the
single standard input format every project's ingestion pipeline must
produce, and how metadata values are typed for filtering.

## 1. Two layers, on purpose

| Layer | File | Knows about | Changes across projects? |
|---|---|---|---|
| **0 — Wire format** | `app/core/schema/document.py` (`DocumentRecord`) | JSON-safe scalars/lists only. Never a field's meaning. | **Never.** This is the one shape `app/core/` may depend on. |
| **1 — Typed metadata** | `app/core/schema/metadata_types.py` (`MetadataFieldDef`, `normalize_metadata`, `validate_document_batch`) | Per-project field declarations, supplied from that project's YAML config. | **Per project.** Every project ships its own list of `MetadataFieldDef`. |

All imports in this module use the `app.core.schema.*` path (matching
this project's existing `app/` package layout — `app/routes.py`,
`app/services.py`, etc.). Since `app/` isn't installed as a package, run
tests and scripts from the repo root with `app/` importable, e.g.:

```bash
PYTHONPATH=. python3 -m pytest tests/
PYTHONPATH=. python3 scripts/regenerate_json_schema.py
```

or equivalently `python3 -m pytest` / `python3 -m scripts.regenerate_json_schema`
if your existing test runner is already configured to put the repo root
on `sys.path` (many `pytest.ini`/`pyproject.toml` setups do this
automatically — check yours before assuming `PYTHONPATH` is needed).

This split exists so `DocumentRecord` — the thing `core/` search, ranking,
and pagination code touches — never needs to change no matter how many
projects fork this repo. All the "what does `promulgation_date` mean and
what type is it" knowledge lives in Layer 1, driven by config, exactly as
required by source-doc §7 and §9 ("the engine ... does not need to know
in advance what a 'promulgation date' or 'document type' means").

## 2. Layer 0 — `DocumentRecord`

```json
{ "id": "string", "text": "string", "metadata": { "...": "..." } }
```

Rules, all enforced at validation time (not discovered later at query
time):

- `id`: required, non-blank, unique **within a batch** (batch-level
  uniqueness is checked by `validate_document_batch`, not by the model
  itself — a single record can't know about its siblings).
- `text`: required. Empty string (`""`) is valid and must be used
  explicitly — omitting the key is a validation error, not equivalent to
  `""`.
- `metadata`: a **flat** `dict[str, scalar | list[scalar]]`. No nested
  objects, no nested lists, no list-of-objects. This is deliberately
  restrictive — see §6, "Deferred / explicitly out of scope."
- No extra top-level keys are allowed (`extra="forbid"`) — an ingestion
  bug that bolts on a stray field (e.g. an ad hoc `embedding` key) fails
  loudly instead of silently passing through.

The canonical JSON Schema is checked in at `app/core/schema/document.schema.json`,
generated from the Pydantic model by `scripts/regenerate_json_schema.py` —
**never hand-edit the `.json` file**; regenerate it and commit the diff.
This lets non-Python tooling (a data-prep script in another language, a CI
validation step) validate raw files before they ever reach the Python
ingestion pipeline.

**Known limitation of the JSON Schema export:** a few rules — "no nested
lists," "no list of objects," "metadata keys must not be blank" — are
enforced by custom Pydantic validators that don't translate into plain
JSON Schema. The exported schema catches structural/type-level violations;
these specific shape rules are only fully enforced by the Python
`DocumentRecord` validator. If non-Python producers need these caught
pre-ingestion too, that's a candidate for a follow-up (e.g. a small CLI
wrapping the Python validator), not yet built in v0.

## 3. Layer 1 — Metadata field types

Six field types cover the source doc's requirement (§7: "string, date,
int, float, bool, list"):

| `MetadataFieldType` | Python type after normalization | Raw JSON wire form accepted |
|---|---|---|
| `STRING` | `str` | JSON string only |
| `DATE` | `datetime.date` | JSON string, strict `YYYY-MM-DD`, real calendar date |
| `INT` | `int` | JSON integer only (**not** `true`/`false`, **not** `5.0`) |
| `FLOAT` | `float` | JSON integer or float (**not** `true`/`false`) |
| `BOOL` | `bool` | JSON boolean only (**not** `1`/`0`/`"true"`) |
| `LIST` | `list[T]` where `T` is one of the above scalars | JSON array of the declared `item_type`'s wire form; must be flat (no nested lists) |

### Why coercion is strict, not lenient

Every "not" above is intentional. A lenient coercion (e.g. treating `1`
as `true`, or `5.0` as `5`) hides a data-quality bug at ingestion time and
turns it into a silently-wrong filter result at query time, potentially
much later and much harder to trace. **Ingestion is the cheapest place to
catch a type mismatch** — so `normalize_metadata` fails on it there,
loudly, with the offending field and raw value named in the error.

The one specific trap worth calling out: Python's `bool` is a subclass of
`int` (`isinstance(True, int)` is `True`), so a naive `isinstance(x, int)`
check would silently accept booleans into an `INT` field. Both `INT` and
`FLOAT` coercion explicitly reject `bool` before checking for their real
type — this is tested directly (`test_int_field_rejects_bool_even_though_bool_is_a_python_int_subclass`).

### `required` — the only presence flag

A field is either `required=True` (must be present in raw metadata and
non-null, or it's a validation error) or `required=False` (default —
missing key or explicit JSON `null` both normalize to Python `None`,
without an error). There is deliberately no separate `nullable` flag:
one flag with one clear meaning is harder to misconfigure than two flags
that can contradict each other.

**Every declared field is guaranteed to be a key in the normalized
output**, even when absent from a given record's raw metadata (value
`None` if optional-and-missing). This means the filtering engine (Phase
1) can always do `record.metadata["some_declared_field"]` without a
`KeyError`, regardless of which records happen to have that field
populated.

For `LIST` fields specifically: optional-and-missing normalizes to
`None`, **not** `[]`. An empty list `[]` is a distinct, valid, *present*
value (e.g. "we checked and there genuinely are no cross-references"),
different from "this field wasn't populated for this record." Don't
conflate the two downstream.

### Unknown (undeclared) metadata fields

Controlled by `unknown_field_policy`:

- **`"passthrough"` (default).** A raw metadata key not declared in the
  project's schema is kept, untyped, in the normalized output. It's
  simply never referenceable by a config-declared filter (filters only
  ever name declared fields), but it remains available for display. This
  matches source-doc §9's principle that the engine doesn't need to know
  every field up front.
- **`"strict"`.** Any undeclared key is a validation error. Use this for
  a project that wants ingestion to catch typos (a raw key that was
  *meant* to match a declared field name but doesn't, e.g. `pubdate` vs.
  the declared `publication_date`).

## 4. Batch validation — what ingestion actually calls

`validate_document_batch(records, schema)` is the one function a
project's ingestion pipeline should call, not `normalize_metadata`
directly per record. It:

1. Runs `normalize_metadata` per record, **collecting every error across
   every field** rather than stopping at the first one — a bulk ingestion
   run should surface its entire problem list in one pass, not one error
   per re-run.
2. Detects **duplicate ids across the whole batch** (impossible to check
   per-record in isolation) and excludes **all** copies of a duplicated
   id from the valid set — there's no principled way to auto-pick which
   copy is "correct," so the batch report flags it for a human instead.
3. Never partially includes a record: a record with *any* field error is
   entirely excluded from `valid_documents`, never included with some
   fields typed and others silently null. This guarantees the filtering
   engine downstream never operates on a half-typed record without
   knowing it.
4. Returns a full report (`BatchValidationResult`: valid documents +
   per-record errors + duplicate ids + `.is_clean` + `.summary`) instead
   of raising — the caller (ingestion pipeline, or a CI check) decides
   whether any errors are fatal for that run.

## 5. Type → filter operation compatibility matrix

This is the contract the Phase 1 / Track B YAML config loader uses to
reject an invalid config (e.g. a `contains` operation declared on a
`BOOL` field) **at config load time**, per the requirement that bad
configs "fail loudly ... not at query time."

| Type | Allowed operations | Notes |
|---|---|---|
| `STRING` | `equality`, `contains` | |
| `DATE` | `equality`, `range` | |
| `INT` | `equality`, `range` | |
| `FLOAT` | `equality`, `range` | |
| `BOOL` | `equality` | `range`/`contains` don't have a sensible meaning for a boolean |
| `LIST` | `contains` | Defined as **membership**: value ∈ list (e.g. `"subjects" contains "Trade"`). This is the only list operation v0 gives a defined meaning — see §6. |

`is_operation_compatible(field_type, operation)` is the function call the
config loader should use; a companion test
(`test_every_field_type_has_a_compatibility_entry`) guards against a
future new `MetadataFieldType` silently having no allowed operations at
all if someone forgets to update the matrix.

This matrix is intentionally small (only the three operations from
source-doc §3). **Extend it deliberately and update this table** when a
new operation is added to the generic core — don't let a project add an
operation ad hoc in its custom layer without this document changing too.

## 6. Deferred / explicitly out of scope for v0

Documented here specifically so nobody "fixes" these ad hoc in a single
project's copy later, creating drift. If one of these becomes a real,
recurring need, promote it to the core deliberately (per the source
doc's §4 promotion principle) and update this document.

- **Nested metadata objects.** Metadata is flat only. A project needing
  structured nested metadata should flatten it at ingestion time (e.g.
  `address.city` → a top-level `address_city` field) rather than the
  core schema growing dotted-path support.
- **`DATETIME` (date + time-of-day).** Only date-only (`YYYY-MM-DD`) is
  supported. Add a `DATETIME` type only when a real project needs
  time-of-day filtering, not speculatively.
- **Lenient/loose type coercion** (numeric strings, `"true"`/`"false"`,
  truncating floats to ints). Deliberately not supported — see §3, "Why
  coercion is strict."
- **Richer list operations** beyond membership — e.g. "contains all of
  [x, y]" (set-intersection style, similar to source-doc §2's
  `mandatories` boolean logic but for a metadata field rather than
  lexical search terms), or "intersects any of." If a real use case needs
  this on a metadata filter (as opposed to lexical search, which already
  has its own boolean logic per §2), add it as a new operation in this
  matrix, not as a custom per-project workaround.
- **A `default` value** for missing optional fields (currently always
  `None`/`[]`-is-not-default). Add only if a real config needs it.

## 7. Keeping the JSON Schema in sync

`app/core/schema/document.schema.json` is generated, not hand-authored:

```bash
python scripts/regenerate_json_schema.py
```

Run this whenever `app/core/schema/document.py` changes and commit the
resulting diff. Recommended for Phase 6 (hardening): add a CI step that
runs the script and fails the build if it produces an uncommitted diff,
so the checked-in schema can never silently drift from the Pydantic
model it's supposed to mirror.
