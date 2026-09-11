from __future__ import annotations

from app.custom.legal.metadata_extractor import extract_legal_metadata
from app.custom.legal.raw_loader import _add_extracted_metadata


_PAGE = """
الجريدة الرسمية عدد 6889 مكرر - 9 يونيو 2020
مرسوم رقم 2.20.406
بتمديد مدة سريان مفعول حالة الطوارئ الصحية بسائر أرجاء التراب الوطني.
حرر بالرباط في 9 يونيو 2020
الإمضاء: رئيس الحكومة
"""


def test_extracts_filter_metadata_from_selectable_arabic_text():
    metadata = extract_legal_metadata(_PAGE, "BO_6889-bis_Ar.pdf")

    assert metadata["issue_number"] == "6889-bis"
    assert metadata["publication_date"] == "2020-06-09"
    assert metadata["promulgation_date"] == "2020-06-09"
    assert metadata["document_type"] == "decret"
    assert metadata["law_number"] == "2.20.406"
    assert metadata["signatures"] == "رئيس الحكومة"
    assert metadata["subjects"] == ["public_health"]
    assert metadata["mandatory_keywords"] == "public_health"


def test_page_metadata_carries_act_values_and_preserves_sidecar_values():
    records = [
        {
            "id": "BO_6889-bis_Ar.pdf#page=2",
            "text": _PAGE,
            "metadata": {
                "source_file": "BO_6889-bis_Ar.pdf",
                "source_page": 2,
                "file_name": "display-name.pdf",
                "document_type": "custom_type",
                "subjects": ["curated_subject"],
            },
        },
        {
            "id": "BO_6889-bis_Ar.pdf#page=3",
            "text": "المادة الثانية تستمر حالة الطوارئ الصحية.",
            "metadata": {
                "source_file": "BO_6889-bis_Ar.pdf",
                "source_page": 3,
                "file_name": "display-name.pdf",
                "document_type": "bulletin_officiel",
            },
        },
    ]

    _add_extracted_metadata(records)

    first, continuation = records
    assert first["metadata"]["file_name"] == "display-name.pdf"
    assert first["metadata"]["document_type"] == "custom_type"
    assert first["metadata"]["subjects"] == ["curated_subject"]
    assert first["metadata"]["publication_date"] == "2020-06-09"
    assert continuation["metadata"]["document_type"] == "decret"
    assert continuation["metadata"]["law_number"] == "2.20.406"
    assert continuation["metadata"]["subjects"] == ["public_health"]
