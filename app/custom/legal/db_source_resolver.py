"""
app/custom/legal/db_source_resolver.py

A drop-in alternative to `source_resolver.build_pdf_source_resolver()`:
resolves a document's original PDF bytes from the SQLite `sources`
table instead of the filesystem, using the generalized
`SourceFileResolver` contract in `app/api/http.py` (which accepts a
`Path`, `bytes`, or `None` -- not filesystem-only, precisely so this
kind of resolver could exist without a core change beyond the contract
itself).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from app.core.schema.metadata_types import NormalizedDocument


def build_sqlite_source_resolver(db_path: str | Path):
    """Build a resolver that looks up a document's `source_file`
    metadata in the `sources` table and returns that PDF's raw bytes.

    Opens a fresh connection per call rather than holding one open for
    the process lifetime -- source fetches are rare relative to search
    requests, and SQLite connections are cheap to open; this avoids any
    cross-thread connection-sharing concerns in Flask's dev/threaded
    server.
    """
    resolved_db_path = Path(db_path)

    def resolve(document: NormalizedDocument) -> Optional[bytes]:
        source_file = document.metadata.get("source_file")
        if not isinstance(source_file, str) or not source_file.strip():
            return None

        conn = sqlite3.connect(resolved_db_path)
        try:
            row = conn.execute(
                "SELECT pdf_bytes FROM sources WHERE source_file = ?", (source_file,)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None
        return row[0]

    return resolve