"""
scripts/migrate_legal_pdfs_to_sqlite.py

One-time migration for testing DB-backed document storage against the
SAME legal PDFs already used by the file-backed path
(docs/file-backed-ingestion.md). Reuses the EXACT same extraction
pipeline (`extract_pdf_records` + the legal metadata extractor, via
`app.custom.legal.raw_loader.load_raw_records`) that `run_factory.py`
already uses -- this script does not reimplement PDF parsing or legal
metadata extraction, it only adds a new destination for the same
records: a SQLite file instead of leaving them as loose PDFs on disk.

Usage:

    python scripts/migrate_legal_pdfs_to_sqlite.py \
        --documents-dir data/legal_documents/documents_pdf \
        --db-path data/legal_documents/legal.db

`--metadata-path` is optional, same meaning as
`LEGAL_METADATA_PATH`/`load_raw_records`'s own `metadata_path` argument.

Schema (SQLite, stdlib `sqlite3`, no new dependency):

    sources(source_file TEXT PRIMARY KEY, pdf_bytes BLOB NOT NULL)
    documents(id TEXT PRIMARY KEY, text TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              source_file TEXT NOT NULL REFERENCES sources(source_file))

One row in `sources` per original PDF file (the file's raw bytes, once);
one row in `documents` per extracted page-record (matching the existing
one-record-per-page granularity from `extract_pdf_records`), referencing
the PDF it came from by `source_file` -- avoids storing the same PDF's
bytes once per page.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.custom.legal.raw_loader import load_raw_records

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_file TEXT PRIMARY KEY,
    pdf_bytes BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    source_file TEXT NOT NULL REFERENCES sources(source_file)
);
"""


def migrate(documents_dir: Path, db_path: Path, metadata_path: Path | None = None) -> None:
    records = load_raw_records(documents_dir, metadata_path=metadata_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)

        source_files: set[str] = set()
        for record in records:
            source_file = record["metadata"].get("source_file")
            if not source_file:
                raise ValueError(
                    f"record {record['id']!r} has no 'source_file' metadata -- "
                    "cannot migrate a record whose original PDF can't be located"
                )
            source_files.add(str(source_file))

        for source_file in sorted(source_files):
            pdf_path = documents_dir / source_file
            if not pdf_path.is_file():
                raise FileNotFoundError(
                    f"source PDF referenced by extracted records not found: {pdf_path}"
                )
            conn.execute(
                "INSERT OR REPLACE INTO sources (source_file, pdf_bytes) VALUES (?, ?)",
                (source_file, pdf_path.read_bytes()),
            )

        for record in records:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, text, metadata_json, source_file) "
                "VALUES (?, ?, ?, ?)",
                (
                    record["id"],
                    record["text"],
                    json.dumps(record["metadata"]),
                    record["metadata"]["source_file"],
                ),
            )

        conn.commit()
    finally:
        conn.close()

    print(
        f"Migrated {len(records)} document record(s) from {len(source_files)} "
        f"PDF file(s) into {db_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents-dir", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--metadata-path", type=Path, default=None)
    args = parser.parse_args()

    migrate(args.documents_dir, args.db_path, args.metadata_path)


if __name__ == "__main__":
    main()