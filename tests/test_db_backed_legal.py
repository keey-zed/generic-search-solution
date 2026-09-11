"""
tests/test_db_backed_legal.py

Tests for the DB-backed alternative to the file-backed legal ingestion
path: db_raw_loader.py, db_source_resolver.py, bootstrap.py's db_path
branch, and the migration script. None of these need real PDFs -- a
small synthetic SQLite database (built directly with sqlite3, not via
the migration script) is enough to prove the loader/resolver contract
holds; the migration script itself is tested separately with a tiny
real PDF-like fixture.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.api.http import create_http_app
from app.custom.legal.bootstrap import build_search_engine
from app.custom.legal.db_raw_loader import load_raw_records_from_db
from app.custom.legal.db_source_resolver import build_sqlite_source_resolver
from app.core.schema.metadata_types import NormalizedDocument


def _make_db(path: Path, rows: list[tuple[str, str, dict, str]], sources: dict[str, bytes]) -> None:
    """rows: list of (id, text, metadata_dict, source_file)."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sources (source_file TEXT PRIMARY KEY, pdf_bytes BLOB NOT NULL);
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, text TEXT NOT NULL,
                metadata_json TEXT NOT NULL, source_file TEXT NOT NULL
            );
            """
        )
        for source_file, pdf_bytes in sources.items():
            conn.execute("INSERT INTO sources VALUES (?, ?)", (source_file, pdf_bytes))
        for doc_id, text, metadata, source_file in rows:
            conn.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?)",
                (doc_id, text, json.dumps(metadata), source_file),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def sample_db(tmp_path) -> Path:
    db_path = tmp_path / "legal.db"
    _make_db(
        db_path,
        rows=[
            (
                "legal-1",
                "Dahir sample text",
                {"document_type": "dahir", "title": "Loi 1", "source_file": "BO-1.pdf"},
                "BO-1.pdf",
            ),
            (
                "legal-2",
                "Marsoum sample text",
                {"document_type": "marsoum", "title": "Loi 2", "source_file": "BO-2.pdf"},
                "BO-2.pdf",
            ),
        ],
        sources={"BO-1.pdf": b"%PDF-1.4 fake pdf one", "BO-2.pdf": b"%PDF-1.4 fake pdf two"},
    )
    return db_path


# ---------------------------------------------------------------------------
# db_raw_loader
# ---------------------------------------------------------------------------


def test_load_raw_records_from_db_returns_standard_shape(sample_db):
    records = load_raw_records_from_db(sample_db)
    assert len(records) == 2
    ids = {r["id"] for r in records}
    assert ids == {"legal-1", "legal-2"}
    record = next(r for r in records if r["id"] == "legal-1")
    assert record["text"] == "Dahir sample text"
    assert record["metadata"]["document_type"] == "dahir"


def test_load_raw_records_from_db_missing_file_raises():
    with pytest.raises(FileNotFoundError, match="not found"):
        load_raw_records_from_db("/nonexistent/path/legal.db")


def test_load_raw_records_from_db_empty_database_returns_empty_list(tmp_path):
    db_path = tmp_path / "empty.db"
    _make_db(db_path, rows=[], sources={})
    assert load_raw_records_from_db(db_path) == []


def test_load_raw_records_from_db_corrupt_metadata_raises(tmp_path):
    db_path = tmp_path / "corrupt.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sources (source_file TEXT PRIMARY KEY, pdf_bytes BLOB NOT NULL);
        CREATE TABLE documents (
            id TEXT PRIMARY KEY, text TEXT NOT NULL,
            metadata_json TEXT NOT NULL, source_file TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?)", ("bad-1", "text", "{not valid json", "x.pdf")
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="corrupt metadata_json"):
        load_raw_records_from_db(db_path)


# ---------------------------------------------------------------------------
# db_source_resolver
# ---------------------------------------------------------------------------


def _doc(source_file):
    return NormalizedDocument(id="d1", text="t", metadata={"source_file": source_file})


def test_sqlite_source_resolver_returns_bytes(sample_db):
    resolver = build_sqlite_source_resolver(sample_db)
    result = resolver(_doc("BO-1.pdf"))
    assert result == b"%PDF-1.4 fake pdf one"


def test_sqlite_source_resolver_returns_none_for_unknown_source_file(sample_db):
    resolver = build_sqlite_source_resolver(sample_db)
    assert resolver(_doc("nonexistent.pdf")) is None


def test_sqlite_source_resolver_returns_none_when_metadata_missing_source_file(sample_db):
    resolver = build_sqlite_source_resolver(sample_db)
    doc = NormalizedDocument(id="d1", text="t", metadata={})
    assert resolver(doc) is None


# ---------------------------------------------------------------------------
# bootstrap.py's db_path branch, and end-to-end through the HTTP layer
# ---------------------------------------------------------------------------


def test_build_search_engine_rejects_both_documents_dir_and_db_path(sample_db):
    with pytest.raises(ValueError, match="not both"):
        build_search_engine(documents_dir="/some/dir", db_path=sample_db)


def test_build_search_engine_from_db_path_builds_a_working_engine(sample_db):
    engine = build_search_engine(db_path=sample_db)
    assert engine.get_document("legal-1") is not None
    assert engine.get_document("legal-2") is not None


def test_db_backed_engine_serves_source_bytes_over_http(sample_db):
    engine = build_search_engine(db_path=sample_db)
    app = create_http_app(engine, source_file_resolver=build_sqlite_source_resolver(sample_db))
    with app.test_client() as client:
        response = client.get("/api/documents/legal-1/source")
    assert response.status_code == 200
    assert response.data == b"%PDF-1.4 fake pdf one"


def test_db_backed_engine_search_and_config_endpoints_work_identically(sample_db):
    """The API contract is identical regardless of storage backend --
    the whole point of this deliverable."""
    engine = build_search_engine(db_path=sample_db)
    app = create_http_app(engine, source_file_resolver=build_sqlite_source_resolver(sample_db))
    with app.test_client() as client:
        config_response = client.get("/api/config")
        assert config_response.status_code == 200
        assert "document_type" in {f["name"] for f in config_response.get_json()["filters"]}

        search_response = client.post("/api/search", json={"lexical": {"first_of": ["Dahir"]}})
        assert search_response.status_code == 200
        hits = search_response.get_json()["hits"]
        assert any(hit["id"] == "legal-1" for hit in hits)


# ---------------------------------------------------------------------------
# Migration script
# ---------------------------------------------------------------------------


def test_migration_script_produces_a_db_loadable_by_db_raw_loader(tmp_path, monkeypatch):
    from scripts.migrate_legal_pdfs_to_sqlite import migrate

    documents_dir = tmp_path / "pdfs"
    documents_dir.mkdir()
    fake_records = [
        {"id": "p1", "text": "hello", "metadata": {"source_file": "a.pdf", "document_type": "dahir"}},
    ]

    # Stub load_raw_records so this test doesn't need a real PDF parser
    # or a real PDF file's byte structure -- only the migration script's
    # OWN logic (writing sources/documents rows from whatever
    # load_raw_records returns) is under test here.
    monkeypatch.setattr(
        "scripts.migrate_legal_pdfs_to_sqlite.load_raw_records", lambda *_a, **_k: fake_records
    )
    (documents_dir / "a.pdf").write_bytes(b"%PDF-1.4 real-enough-for-this-test")

    db_path = tmp_path / "out.db"
    migrate(documents_dir, db_path)

    records = load_raw_records_from_db(db_path)
    assert records == fake_records

    resolver = build_sqlite_source_resolver(db_path)
    assert resolver(_doc("a.pdf")) == b"%PDF-1.4 real-enough-for-this-test"


def test_migration_script_raises_if_source_pdf_missing(tmp_path, monkeypatch):
    from scripts.migrate_legal_pdfs_to_sqlite import migrate

    documents_dir = tmp_path / "pdfs"
    documents_dir.mkdir()
    fake_records = [
        {"id": "p1", "text": "hello", "metadata": {"source_file": "missing.pdf"}},
    ]
    monkeypatch.setattr(
        "scripts.migrate_legal_pdfs_to_sqlite.load_raw_records", lambda *_a, **_k: fake_records
    )

    with pytest.raises(FileNotFoundError):
        migrate(documents_dir, tmp_path / "out.db")