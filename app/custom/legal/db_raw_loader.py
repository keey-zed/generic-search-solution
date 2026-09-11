"""
app/custom/legal/db_raw_loader.py

A drop-in alternative to `raw_loader.load_raw_records(documents_dir=...)`:
reads the same shape of records from the SQLite database produced by
`scripts/migrate_legal_pdfs_to_sqlite.py`, instead of extracting PDFs
from a directory on every startup.

Returns the exact same `{id, text, metadata}` shape either way --
`app.core.ingestion.ingest_raw_records()` (called by bootstrap.py)
neither knows nor cares whether a record came from a live PDF extraction
or a database row. This file is the ONLY place that knows records are
stored in SQLite.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def load_raw_records_from_db(db_path: str | Path) -> list[dict[str, Any]]:
    """Read every row from the `documents` table and return it as a raw
    record. Raises FileNotFoundError if the database file doesn't exist
    -- a missing DB is a setup error, not a valid "empty corpus" state
    (that's still representable as a DB with zero rows, which returns
    `[]` normally below)."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"legal database not found: {path} -- run "
            "scripts/migrate_legal_pdfs_to_sqlite.py first"
        )

    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, text, metadata_json FROM documents").fetchall()
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"corrupt metadata_json for document {row['id']!r} in {path}: {exc}"
            ) from exc
        records.append({"id": row["id"], "text": row["text"], "metadata": metadata})

    return records