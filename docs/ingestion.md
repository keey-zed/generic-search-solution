# Ingestion & Normalization Layer

This document specifies **Phase 1, Track B, Task 1**: the layer that
turns a project's raw data into the standard, validated, typed shape the
rest of core (filtering, ranking, retrieval) is allowed to depend on.

Read `docs/metadata-typing.md` and `docs/config-schema.md` first — this
layer is thin specifically because it reuses everything those already
built, rather than re-implementing any of it.

```bash
PYTHONPATH=. python3 -m pytest tests/test_ingestion.py
```

## 1. Where this fits, and why it's thin

```
Project's raw data (XML dump, CSV, API, ...)
        │
        │   <-- project-specific extraction, lives in app/custom/<project>/,
        │       NOT built here. Its only job: produce plain dicts shaped
        │       like {"id": ..., "text": ..., "metadata": {...}}.
        ▼
   list[dict]  +  embeddings: dict[id, Embedding]  (optional)
        │
        ▼
  ingest_raw_records()          <-- app/core/ingestion/loader.py, this deliverable
        │
        ▼
     IngestionReport
   ├─ valid_documents: list[IngestedDocument]
   ├─ record_errors:   list[RecordIngestionError]
   ├─ duplicate_ids:   list[str]
   └─ unmatched_embedding_ids: list[str]
```

`ingest_raw_records()` does not parse XML, scrape a CSV, or know
anything about where a project's data comes from — that's deliberately
out of scope here and belongs to each project's custom layer later. What
it does is call, once each, in order, on every record in a batch:

1. **Wire-format validation** — `DocumentRecord` (Phase 0). Is this dict
   even shaped like `{id, text, metadata}`, with flat metadata, a
   non-blank id, etc.?
2. **Metadata typing** — `metadata_types.validate_document_batch()`
   (Phase 0). Given the project's declared `MetadataSchema`, does each
   field's *value* coerce to the declared type? Are required fields
   present? Are ids unique across the whole batch?
3. **Embedding attachment** — look up `embeddings[record.id]` (Phase 0
   deliverable 2's `Embedding`) and attach it, or leave it `None`.

None of the actual type-coercion or duplicate-id logic is reimplemented
here — step 2 is one function call into the exact code
`docs/metadata-typing.md` already documents. This module's job is purely
to wire the three steps together and turn every possible failure into
one consistent, per-record report.

## 2. Two kinds of error, reported the same way

A record can fail for two structurally different reasons, and this
module keeps them labeled apart (`RecordIngestionError.stage`) because
they point a developer to different places:

| Stage | Example | Means |
|---|---|---|
| `wire_format` | missing `text`, blank `id`, nested metadata object | The raw record itself is broken — independent of any project's config. |
| `metadata_typing` | `document_type: 123` when the schema says `string`; a required field missing | The record's *shape* is fine, but its *content* doesn't match what this project declared in `config.yaml`. |

Both report through the same shape — `RecordIngestionError(record_id,
stage, errors: list[FieldError])`, reusing `FieldError` exactly as
`normalize_metadata()` already defined it — so a caller only ever
handles one error format regardless of which stage produced it.

Every problem in a batch is collected in one pass (never raises on the
first bad record), matching the "fail loud and collect everything"
principle the rest of Phase 0 already follows — a real ingestion run
needs the full list of bad records in one go, not one error per re-run.

A record with **any** error — wire-format or typing — is excluded from
`valid_documents` entirely. There is no partial/half-typed record in the
output for filtering to accidentally operate on.

## 3. `IngestedDocument` — the standard ingestion output

```python
class IngestedDocument(NormalizedDocument):   # id, text, metadata: TypedMetadataValue
    embedding: Optional[Embedding] = None
```

This mirrors the same pattern `EmbeddedDocumentRecord` used in Phase 0
deliverable 2 (a subclass adding one optional field), applied one layer
up: `EmbeddedDocumentRecord` pairs an embedding with the *raw* wire-format
record; `IngestedDocument` pairs an embedding with the *typed,
normalized* record — the shape filtering actually needs (real `date`
objects for range filters, not date strings).

`embedding` is optional for the same reason it's optional everywhere
else in this project: a document ingested before its embedding job has
run, or from a project that hasn't adopted embeddings, is a normal state
— not an error.

**Compatibility with `InlineEmbeddingProvider` is automatic.**
`InlineEmbeddingProvider` only ever touches `.id` and `.embedding` on
whatever it's given — it doesn't require `EmbeddedDocumentRecord`
specifically. So `IngestionReport.valid_documents` can be passed straight
into it with no conversion step:

```python
report = ingest_raw_records(raw_records, schema, embeddings=embeddings)
provider = InlineEmbeddingProvider(report.valid_documents)
```

## 4. Unmatched embeddings

`unmatched_embedding_ids` lists every id in the `embeddings` argument
that never ended up attached to a valid document — because no record
with that id was supplied, or because the record with that id failed
validation (wire-format or typing) or was dropped as a duplicate. This
isn't an error (ingestion still succeeds), but it's almost always a sign
of an id mismatch between a project's raw data and its precomputed
embeddings, and is cheap to surface rather than silently dropping it.

## 5. Wiring it to the config layer

`schema` is whatever `MetadataSchema` a project declares — in practice,
that's `UseCaseConfig.to_metadata_schema()` from the config layer
(`app/core/config/models.py`), so a project's `config.yaml` is the single
source of truth for both what filters exist (Track B, task 2/3) and what
ingestion will accept:

```python
from app.core.config import load_use_case_config
from app.core.ingestion import ingest_raw_records

config = load_use_case_config("app/custom/legal/config.yaml")
schema = config.to_metadata_schema()

report = ingest_raw_records(raw_records, schema, embeddings=embeddings)
if not report.is_clean:
    for err in report.record_errors:
        print(err.record_id, err.stage, [e.message for e in err.errors])
```

## 6. What's deliberately not built here

- **No project-specific extraction** (XML/CSV/API parsing). Belongs in
  `app/custom/<project>/`, producing the plain-dict shape this module
  expects as input.
- **No embedding computation.** `embeddings` is a precomputed
  `dict[id, Embedding]`, supplied by whatever ran the embedding model —
  this layer only attaches, never generates, vectors.
- **No storage/persistence.** `ingest_raw_records()` is a pure
  function — it returns an `IngestionReport` in memory. Where
  `valid_documents` end up living (a pickle, a database, a vector
  index, ...) is a separate concern for a later deliverable.