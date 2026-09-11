"""
app/custom/legal/raw_loader.py

The legal project's own `load_raw_records()`, filled in following
app/custom/_template/raw_loader.py's pattern.

The no-argument form retains the small embedded corpus used by the
template tests.  Pass ``documents_dir`` to extract an actual directory of
PDFs (such as Bulletin Officiel files) instead.  The extraction stays in
this custom layer; ``app.core`` still only receives its generic
``{id, text, metadata}`` wire format.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.ingestion import extract_pdf_records

from .metadata_extractor import extract_legal_metadata

_SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "id": "legal-1",
        "text": "Dahir portant loi de finances pour l'annee budgetaire 2020, relatif aux dispositions fiscales.",
        "metadata": {
            "mandatory_keywords": "finances fiscales",
            "document_type": "dahir",
            "signatures": "الملك",
            "file_name": "BO-2020-01.pdf",
            "law_number": "20-01",
            "publication_date": "2019-12-31",
            "promulgation_date": "2019-12-30",
            "subjects": ["finance", "fiscalite"],
            "title": "Loi de finances 2020",
        },
    },
    {
        "id": "legal-2",
        "text": "Marsoum relatif a l'organisation du ministere de la sante et a la reforme du secteur hospitalier.",
        "metadata": {
            "mandatory_keywords": "sante administration",
            "document_type": "marsoum",
            "signatures": "رئيس الحكومة",
            "file_name": "BO-2021-12.pdf",
            "law_number": "21-12",
            "publication_date": "2021-03-15",
            "promulgation_date": None,
            "subjects": ["sante", "administration"],
            "title": "Reforme du secteur hospitalier",
        },
    },
    {
        "id": "legal-3",
        "text": "9anoun relatif a la protection des donnees a caractere personnel et a la vie privee.",
        "metadata": {
            "mandatory_keywords": "donnees personnelles",
            "document_type": "9anoun",
            "signatures": "الملك",
            "file_name": "BO-2022-24.pdf",
            "law_number": "22-24",
            "publication_date": "2022-06-01",
            "promulgation_date": "2022-05-20",
            "subjects": ["donnees personnelles", "vie privee"],
            "title": "Protection des donnees personnelles",
        },
    },
    {
        "id": "legal-4",
        "text": "Dahir portant promulgation de la loi relative a l'education et a la formation professionnelle.",
        "metadata": {
            "mandatory_keywords": "education formation",
            "document_type": "dahir",
            "signatures": "الملك",
            "file_name": "BO-2020-42.pdf",
            "law_number": "20-42",
            "publication_date": "2020-09-10",
            "promulgation_date": "2020-09-01",
            "subjects": ["education", "formation professionnelle"],
            "title": "Loi sur l'education",
        },
    },
]


def _load_metadata_sidecar(metadata_path: Path | None) -> Mapping[str, Mapping[str, Any]]:
    if metadata_path is None or not metadata_path.exists():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON metadata sidecar {metadata_path}: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, dict) for key, value in data.items()):
        raise ValueError(
            f"metadata sidecar {metadata_path} must be an object mapping PDF paths/names to metadata objects"
        )
    return data


def load_raw_records(
    documents_dir: str | Path | None = None,
    *,
    metadata_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return sample records, or page-level records extracted from PDFs.

    ``metadata_path`` is an optional JSON object keyed by a PDF filename
    or its path relative to ``documents_dir``.  It supplies real legal
    metadata (publication date, subjects, title, etc.) without hardcoding
    any filename or legal parsing rule in the generic extractor.
    """
    if documents_dir is None:
        return _SAMPLE_RECORDS

    directory = Path(documents_dir)
    if not directory.is_dir():
        raise ValueError(f"PDF source directory does not exist or is not a directory: {directory}")
    sidecar = Path(metadata_path) if metadata_path is not None else directory / "metadata.json"
    extraction = extract_pdf_records(
        directory,
        metadata_by_source=_load_metadata_sidecar(sidecar),
        # A BO issue is the indexed document here.  Sidecar metadata can
        # override this with a more specific project taxonomy.
        default_metadata={"document_type": "bulletin_officiel"},
    )

    # `source_file` is generic extractor provenance. The legal UI also
    # exposes a project-level `file_name` field; for one-PDF-per-issue input
    # it is a truthful, useful default even when no optional metadata sidecar
    # has been provided. A sidecar remains authoritative if it supplies a
    # different display value.
    for record in extraction.records:
        metadata = record["metadata"]
        metadata.setdefault("file_name", metadata["source_file"])

    _add_extracted_metadata(extraction.records)

    errors = [issue for issue in extraction.issues if issue.severity == "error"]
    if errors:
        details = "; ".join(
            f"{issue.path}{f' page {issue.page_number}' if issue.page_number else ''}: {issue.message}"
            for issue in errors
        )
        raise ValueError(f"PDF extraction failed: {details}")
    if not extraction.records:
        raise ValueError(
            f"no searchable native text was extracted from {directory}; "
            "the PDFs may be scanned and require an OCR stage"
        )
    return extraction.records


_ISSUE_FIELDS = {"publication_date", "issue_number"}
_ACT_FIELDS = {
    "document_type",
    "law_number",
    "promulgation_date",
    "signatures",
    "subjects",
    "mandatory_keywords",
    "title",
}


def _add_extracted_metadata(records: list[dict[str, Any]]) -> None:
    """Enrich page records while preserving sidecar values.

    ``extract_pdf_records`` intentionally knows nothing about legal fields.
    This custom layer supplies them from selectable text.  Issue-level values
    are propagated to every page; act-level values are carried forward across
    continuation pages until a later page exposes a new value.  A value that
    already exists (for example, from ``metadata.json``) is authoritative.
    """
    if not records:
        return

    records_by_source: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source_file = str(record["metadata"].get("source_file", ""))
        records_by_source.setdefault(source_file, []).append(record)

    for source_file, source_records in records_by_source.items():
        combined_text = "\n".join(str(record.get("text", "")) for record in source_records)
        issue_metadata = extract_legal_metadata(combined_text, source_file)
        carried: dict[str, Any] = {}

        for record in sorted(
            source_records,
            key=lambda item: int(item["metadata"].get("source_page", 0)),
        ):
            metadata = record["metadata"]
            page_metadata = extract_legal_metadata(record.get("text", ""), source_file)

            # Sidecar/file metadata wins. Auto extraction only fills missing
            # fields, except for the generic default document type.
            for field in _ISSUE_FIELDS:
                if field not in metadata and field in issue_metadata:
                    metadata[field] = issue_metadata[field]

            if metadata.get("document_type") in (None, "bulletin_officiel"):
                page_type = page_metadata.get("document_type")
                detected_type = (
                    page_type
                    if page_type and page_type != "bulletin_officiel"
                    else issue_metadata.get("document_type")
                )
                if detected_type:
                    metadata["document_type"] = detected_type

            for field in _ACT_FIELDS - {"document_type"}:
                if field in page_metadata:
                    carried[field] = page_metadata[field]
                if field not in metadata and field in carried:
                    metadata[field] = carried[field]
