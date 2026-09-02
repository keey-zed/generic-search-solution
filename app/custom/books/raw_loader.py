"""
app/custom/books/raw_loader.py

The book project's `load_raw_records()`, following
app/custom/_template/raw_loader.py's pattern -- see that file and
app/custom/legal/raw_loader.py for the general shape.

Includes, deliberately, the exact scenario source doc §4 describes: a
classical work (Ibn Sa'd's biographical dictionary) whose title is
commonly transliterated several different ways from Arabic
("Al-Tabaqat al-Kubra" / "Kitab al-Tabaqat al-Kubra" / "al-Tabaqat
al-Kabir", among others) -- a user typing the transliteration they know
may not match the exact spelling stored in the catalog. This is what
`fuzzy_title_filter.py` exists to handle; see docs/fuzzy-title-filter.md.
"""
from __future__ import annotations

from typing import Any

_SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "id": "book-1",
        "text": "A biographical dictionary of the Prophet's companions and the following generations.",
        "metadata": {
            "title": "Kitab al-Tabaqat al-Kabir",
            "author": "Ibn Sa'd",
            "publication_year": 845,
            "subjects": ["biography", "hadith", "early islam"],
        },
    },
    {
        "id": "book-2",
        "text": "A history of the city of Damascus and its notable inhabitants.",
        "metadata": {
            "title": "Tarikh Dimashq",
            "author": "Ibn Asakir",
            "publication_year": 1176,
            "subjects": ["history", "damascus"],
        },
    },
    {
        "id": "book-3",
        "text": "A treatise on grammar and rhetoric.",
        "metadata": {
            "title": "Al-Kitab",
            "author": "Sibawayh",
            "publication_year": 796,
            "subjects": ["grammar", "linguistics"],
        },
    },
]


def load_raw_records() -> list[dict[str, Any]]:
    return _SAMPLE_RECORDS