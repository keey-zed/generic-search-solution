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

_SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "id": "legal-1",
        "text": "Dahir portant loi de finances pour l'annee budgetaire 2020, relatif aux dispositions fiscales.",
        "metadata": {
            "document_type": "dahir",
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
            "document_type": "marsoum",
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
            "document_type": "9anoun",
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
            "document_type": "dahir",
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
