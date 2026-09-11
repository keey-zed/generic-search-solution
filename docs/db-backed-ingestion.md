# DB-backed ingestion

An alternative to `docs/file-backed-ingestion.md`, using the **same
legal PDFs, the same extraction pipeline, the same config.yaml, and the
same API contract** — the only thing that changes is where documents and
source files live: a SQLite database instead of loose files on disk.

## Why this needed a small core change, and only one

`app/api/http.py`'s `/documents/<id>/source` route used to assume every
`source_file_resolver` returns a filesystem `Path`. A database can't
hand back a `Path` — the file doesn't exist on disk, it's a BLOB in a
table. `SourceFileResolver`'s contract was generalized (not
legal-specific — any non-filesystem storage, e.g. object storage, would
hit the same wall) to accept `Path | bytes | None`:

```python
SourceFileResolver = Callable[[NormalizedDocument], Union[Path, bytes, None]]
```

Nothing else under `app/core/` or `app/api/` changed. `POST /search`,
`GET /api/config`, `GET /api/facets`, and `GET /api/documents/<id>`
return byte-for-byte identical JSON shapes regardless of storage backend
— see `tests/test_db_backed_legal.py::test_db_backed_engine_search_and_config_endpoints_work_identically`.
The frontend needs zero changes.

## One-time migration

Reuses `app/custom/legal/raw_loader.load_raw_records()` — the exact
same PDF extraction + legal metadata enrichment pipeline
`docs/file-backed-ingestion.md` already documents — and writes its
output into SQLite instead of leaving it as loose files:

```bash
python scripts/migrate_legal_pdfs_to_sqlite.py \
    --documents-dir data/legal_documents/documents_pdf \
    --db-path data/legal_documents/legal.db
```

Schema (stdlib `sqlite3`, no new dependency):

```sql
CREATE TABLE sources (source_file TEXT PRIMARY KEY, pdf_bytes BLOB NOT NULL);
CREATE TABLE documents (
    id TEXT PRIMARY KEY, text TEXT NOT NULL,
    metadata_json TEXT NOT NULL, source_file TEXT NOT NULL REFERENCES sources(source_file)
);
```

One `sources` row per original PDF (its raw bytes, once); one
`documents` row per extracted page-record, referencing which PDF it
came from — the same PDF's bytes aren't duplicated once per page.

## Running the DB-backed server

```bash
python run_factory_db.py
```

A near-exact twin of `run_factory.py` — same embedding model wiring
(`app/custom/legal/config.yaml`'s `search.semantic.embedder`), same
`create_http_app()` call — pointed at `data/legal_documents/legal.db`
by default. Set `LEGAL_DB_PATH` to point elsewhere.

## The two new files this depends on

- **`app/custom/legal/db_raw_loader.py`** — `load_raw_records_from_db(db_path)`,
  a drop-in alternative to `raw_loader.load_raw_records(documents_dir=...)`.
  Reads the `documents` table, returns the exact same
  `{id, text, metadata}` shape. `ingest_raw_records()` (called by
  `bootstrap.py`) neither knows nor cares which one supplied its input.
- **`app/custom/legal/db_source_resolver.py`** — `build_sqlite_source_resolver(db_path)`,
  a drop-in alternative to `source_resolver.build_pdf_source_resolver()`.
  Looks up a document's `source_file` metadata (the same field the file
  extractor already sets — nothing new here) in the `sources` table and
  returns raw bytes, using the generalized resolver contract above.

`bootstrap.build_search_engine()` gained one new, mutually-exclusive-with-`documents_dir`
keyword: `db_path`. Passing it swaps `load_raw_records_from_db()` in for
`raw_loader.load_raw_records()`; everything else (ingestion, filtering,
embedding, `SearchEngine.from_config_path()`) is identical either way.

## What's deliberately not built here

- **A real database server** (Postgres, MySQL). SQLite was chosen
  specifically because this is explicitly a "test out the possibility"
  prototype, not a production migration — zero new infrastructure to
  run, stdlib-only. Swapping SQLite for a real DB server later would
  only touch `db_raw_loader.py`/`db_source_resolver.py`'s connection
  logic — the `SourceFileResolver` contract change and everything else
  in this document already generalizes to any DB, not just SQLite.
- **Live per-search database queries.** Documents are still loaded
  fully into memory at startup (same as the file-backed path) —
  `db_raw_loader.py` reads the whole `documents` table once, at
  `build_search_engine()` time. This is not query-pushdown to the
  database; it's a different *source* for the same in-memory ingestion
  model this project has always used.
- **Migrating metadata sidecar support.** A DB-backed corpus's metadata
  was already baked into `metadata_json` at migration time
  (`load_raw_records()` was called with the sidecar applied, if any,
  during migration) — there's no separate `metadata_path` concept for
  the DB-backed path at query/startup time.