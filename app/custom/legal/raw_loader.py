"""
app/custom/legal/raw_loader.py

The legal project's own `load_raw_records()`, filled in following
app/custom/_template/raw_loader.py's pattern.

A real deployment would parse an actual legal-text XML dump (or
whatever source system this project pulls from) here. Since Phase 3's
job is proving the TEMPLATE and REGISTRATION PATTERN work, not shipping
a real legal corpus, this returns a small embedded sample instead --
enough for tests/test_custom_layer_template.py to build a real
`SearchEngine` and run real searches against it end to end, without any
external data dependency.

Swap the body of this function for real extraction logic (reading a
file, calling an API, querying a database, ...) when this project moves
from "proof the pattern works" to "real deployment" -- nothing else in
this package, or in app/core/ or app/api/, needs to change either way.
"""
from __future__ import annotations

from typing import Any

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


def load_raw_records() -> list[dict[str, Any]]:
    return _SAMPLE_RECORDS