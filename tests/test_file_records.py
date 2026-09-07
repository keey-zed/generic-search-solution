from __future__ import annotations

import pytest

from app.core.ingestion import ingest_raw_records
from app.core.schema.metadata_types import MetadataFieldDef, MetadataFieldType


fitz = pytest.importorskip("fitz")


def _write_pdf(path, pages: list[str]) -> None:
    document = fitz.open()
    try:
        for page_text in pages:
            page = document.new_page()
            if page_text:
                page.insert_text((72, 72), page_text)
        document.save(path)
    finally:
        document.close()


def test_extract_pdf_records_are_page_level_and_ingest_through_core(tmp_path):
    from app.ingestion import extract_pdf_records

    pdf = tmp_path / "issues" / "BO_1.pdf"
    pdf.parent.mkdir()
    _write_pdf(pdf, ["first legal provision", "second legal provision"])

    extraction = extract_pdf_records(
        tmp_path,
        default_metadata={"document_type": "bulletin_officiel"},
        metadata_by_source={
            "issues/BO_1.pdf": {"title": "BO 1", "publication_date": "2024-01-30"}
        },
    )

    assert extraction.is_clean
    assert [record["id"] for record in extraction.records] == [
        "issues/BO_1.pdf#page=1",
        "issues/BO_1.pdf#page=2",
    ]
    assert extraction.records[1]["metadata"]["source_page"] == 2
    assert extraction.records[0]["metadata"]["title"] == "BO 1"

    report = ingest_raw_records(
        extraction.records,
        [
            MetadataFieldDef(name="document_type", type=MetadataFieldType.STRING, required=True),
            MetadataFieldDef(name="publication_date", type=MetadataFieldType.DATE),
        ],
    )
    assert report.is_clean
    assert len(report.valid_documents) == 2


def test_empty_pdf_page_is_reported_and_not_silently_indexed(tmp_path):
    from app.ingestion import extract_pdf_records

    pdf = tmp_path / "scanned.pdf"
    _write_pdf(pdf, [""])

    extraction = extract_pdf_records(pdf)

    assert extraction.records == []
    assert len(extraction.issues) == 1
    assert extraction.issues[0].severity == "warning"
    assert "require OCR" in extraction.issues[0].message


def test_legal_custom_loader_uses_real_pdf_records_not_its_sample(tmp_path):
    from app.custom.legal.raw_loader import load_raw_records

    _write_pdf(tmp_path / "BO_99.pdf", ["real bulletin content"])

    records = load_raw_records(tmp_path)

    assert [record["id"] for record in records] == ["BO_99.pdf#page=1"]
    assert records[0]["text"] == "real bulletin content"
    assert records[0]["metadata"]["document_type"] == "bulletin_officiel"
