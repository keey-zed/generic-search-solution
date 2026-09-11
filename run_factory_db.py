"""
run_factory_db.py

DB-backed twin of run_factory.py: same engine, same HTTP app, same
config.yaml, same embedding model -- the only difference is where
documents and source files come from: a SQLite database (produced by
scripts/migrate_legal_pdfs_to_sqlite.py) instead of a directory of
loose PDF files.

Nothing about app/core/, app/api/, or the frontend contract changes --
GET /api/config, /api/facets, POST /api/search, GET /api/documents/<id>
and its /source route all return the exact same JSON shapes either way.
See docs/db-backed-ingestion.md.

Usage:
    python scripts/migrate_legal_pdfs_to_sqlite.py \
        --documents-dir data/legal_documents/documents_pdf \
        --db-path data/legal_documents/legal.db
    python run_factory_db.py

Then:
    GET  http://localhost:5000/api/health
    POST http://localhost:5000/api/search

Set LEGAL_DB_PATH to point at a different database file.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.api.http import create_http_app
from app.core.config.loader import load_use_case_config
from app.custom.legal.bootstrap import _DEFAULT_CONFIG_PATH, build_search_engine
from app.custom.legal.db_source_resolver import build_sqlite_source_resolver
from app.embeddings import build_text_embedder


def build_engine():
    """Build the legal SearchEngine from a SQLite-backed corpus.

    Same embedding-model wiring as run_factory.py's build_engine() --
    only the data *location* differs (a DB file here vs. a PDF
    directory there); the embedder configuration itself still comes
    from app/custom/legal/config.yaml, same as always.
    """
    repository_root = Path(__file__).resolve().parent
    default_db_path = repository_root / "data" / "legal_documents" / "legal.db"
    db_path = Path(os.environ.get("LEGAL_DB_PATH", str(default_db_path)))

    config = load_use_case_config(_DEFAULT_CONFIG_PATH)
    embedder_config = config.search.semantic.embedder if config.search.semantic.enabled else None
    text_embedder = build_text_embedder(embedder_config) if embedder_config is not None else None
    cache_path = embedder_config.cache_path if embedder_config is not None else None

    engine = build_search_engine(
        db_path=db_path,
        text_embedder=text_embedder,
        embeddings_cache_path=cache_path,
    )
    return engine, db_path


def main() -> None:
    engine, db_path = build_engine()
    app = create_http_app(
        engine,
        source_file_resolver=build_sqlite_source_resolver(db_path),
    )

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "1") == "1"

    print(f" * Generic Search Factory (SQLite-backed corpus: {db_path}) serving on http://{host}:{port}")
    print(f" * Try: GET  http://localhost:{port}/api/health")
    print(f" * Try: GET  http://localhost:{port}/api/config")
    print(f" * Try: GET  http://localhost:{port}/api/facets")
    print(f" * Try: POST http://localhost:{port}/api/search")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()