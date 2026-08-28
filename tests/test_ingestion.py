from datetime import date

import pytest

from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.ingestion.loader import ingest_raw_records
from app.core.schema.embedding import Embedding
from app.core.schema.metadata_types import MetadataFieldDef, MetadataFieldType

LEGAL_SCHEMA = [
    MetadataFieldDef(name="doctype", type=MetadataFieldType.STRING, required=True),
    MetadataFieldDef(name="publication_date", type=MetadataFieldType.DATE, required=False),
    MetadataFieldDef(
        name="subjects", type=MetadataFieldType.LIST, item_type=MetadataFieldType.STRING, required=False
    ),
]


def _emb(vector, model_id="bge-m3"):
    return Embedding(vector=vector, model_id=model_id)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_records_ingested_and_typed():
    raw = [
        {
            "id": "doc-1",
            "text": "hello",
            "metadata": {"doctype": "dahir", "publication_date": "2020-01-01", "subjects": ["tax"]},
        }
    ]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.is_clean
    assert len(report.valid_documents) == 1
    doc = report.valid_documents[0]
    assert doc.id == "doc-1"
    assert doc.metadata["publication_date"] == date(2020, 1, 1)
    assert doc.metadata["subjects"] == ["tax"]
    assert doc.embedding is None


def test_empty_batch_is_clean():
    report = ingest_raw_records([], LEGAL_SCHEMA)
    assert report.is_clean
    assert report.valid_documents == []
    assert report.duplicate_ids == []


def test_embedding_attached_by_id():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir"}}]
    embeddings = {"doc-1": _emb([0.1, 0.2])}
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings=embeddings)
    assert report.valid_documents[0].embedding.vector == [0.1, 0.2]
    assert report.unmatched_embedding_ids == []


def test_document_without_matching_embedding_gets_none():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings={})
    assert report.valid_documents[0].embedding is None


def test_embeddings_none_argument_defaults_cleanly():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings=None)
    assert report.valid_documents[0].embedding is None
    assert report.unmatched_embedding_ids == []


# ---------------------------------------------------------------------------
# Wire-format errors (structurally broken records)
# ---------------------------------------------------------------------------


def test_missing_text_field_reported_as_wire_format_error():
    raw = [{"id": "doc-1", "metadata": {"doctype": "dahir"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert not report.is_clean
    assert report.valid_documents == []
    assert len(report.record_errors) == 1
    err = report.record_errors[0]
    assert err.stage == "wire_format"
    assert err.record_id == "doc-1"


def test_missing_id_field_reported_with_positional_label():
    raw = [{"text": "hello", "metadata": {}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert len(report.record_errors) == 1
    err = report.record_errors[0]
    assert err.stage == "wire_format"
    assert err.record_id == "<record at index 0>"


def test_non_dict_record_reported_clearly():
    raw = ["not-a-dict", {"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert len(report.valid_documents) == 1
    assert len(report.record_errors) == 1
    err = report.record_errors[0]
    assert err.stage == "wire_format"
    assert "mapping" in err.errors[0].message


def test_nested_metadata_object_reported_as_wire_format_error():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"a": {"nested": "no"}}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.record_errors[0].stage == "wire_format"


# ---------------------------------------------------------------------------
# Metadata typing errors (right shape, wrong content)
# ---------------------------------------------------------------------------


def test_wrong_type_metadata_reported_as_typing_error():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": 123}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.valid_documents == []
    assert len(report.record_errors) == 1
    err = report.record_errors[0]
    assert err.stage == "metadata_typing"
    assert err.record_id == "doc-1"


def test_missing_required_field_reported_as_typing_error():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.record_errors[0].stage == "metadata_typing"


def test_malformed_date_reported_as_typing_error():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir", "publication_date": "01/01/2020"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.record_errors[0].stage == "metadata_typing"


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_duplicate_ids_excluded_from_valid_and_reported():
    raw = [
        {"id": "doc-1", "text": "a", "metadata": {"doctype": "dahir"}},
        {"id": "doc-1", "text": "b", "metadata": {"doctype": "marsoum"}},
    ]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert report.valid_documents == []
    assert report.duplicate_ids == ["doc-1"]
    assert not report.is_clean


def test_duplicate_id_embedding_is_unmatched():
    raw = [
        {"id": "doc-1", "text": "a", "metadata": {"doctype": "dahir"}},
        {"id": "doc-1", "text": "b", "metadata": {"doctype": "marsoum"}},
    ]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings={"doc-1": _emb([0.1])})
    assert report.unmatched_embedding_ids == ["doc-1"]


# ---------------------------------------------------------------------------
# Unmatched embeddings
# ---------------------------------------------------------------------------


def test_embedding_for_nonexistent_document_is_unmatched():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings={"doc-999": _emb([0.1])})
    assert report.unmatched_embedding_ids == ["doc-999"]
    assert report.valid_documents[0].embedding is None


def test_embedding_for_a_record_that_failed_validation_is_unmatched():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": 123}}]  # wrong type -> invalid
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings={"doc-1": _emb([0.1])})
    assert report.valid_documents == []
    assert report.unmatched_embedding_ids == ["doc-1"]


# ---------------------------------------------------------------------------
# Batch collection semantics: everything reported in one pass
# ---------------------------------------------------------------------------


def test_mixed_batch_all_problems_collected_in_one_pass():
    raw = [
        {"id": "doc-1", "text": "ok", "metadata": {"doctype": "dahir"}},  # valid
        {"id": "doc-2", "metadata": {"doctype": "dahir"}},  # missing text -> wire_format
        {"id": "doc-3", "text": "bad type", "metadata": {"doctype": 5}},  # metadata_typing
        {"id": "doc-1", "text": "dup", "metadata": {"doctype": "dahir"}},  # duplicate of doc-1
        "garbage",  # non-dict
    ]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)

    # doc-1 is a duplicate id (appears twice) so it's excluded entirely.
    assert report.valid_documents == []
    assert report.duplicate_ids == ["doc-1"]

    stages = {err.record_id: err.stage for err in report.record_errors}
    assert stages["doc-2"] == "wire_format"
    assert stages["doc-3"] == "metadata_typing"
    assert stages["<record at index 4>"] == "wire_format"


def test_summary_reflects_counts():
    raw = [
        {"id": "doc-1", "text": "ok", "metadata": {"doctype": "dahir"}},
        {"id": "doc-2", "metadata": {"doctype": "dahir"}},
    ]
    report = ingest_raw_records(raw, LEGAL_SCHEMA)
    assert "1 valid" in report.summary
    assert "1 record(s) with errors" in report.summary


# ---------------------------------------------------------------------------
# Passthrough of unknown_field_policy
# ---------------------------------------------------------------------------


def test_unknown_field_policy_strict_rejects_undeclared_field():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir", "extra_field": "surprise"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, unknown_field_policy="strict")
    assert report.valid_documents == []
    assert report.record_errors[0].stage == "metadata_typing"


def test_unknown_field_policy_passthrough_keeps_undeclared_field():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {"doctype": "dahir", "extra_field": "kept"}}]
    report = ingest_raw_records(raw, LEGAL_SCHEMA, unknown_field_policy="passthrough")
    assert report.valid_documents[0].metadata["extra_field"] == "kept"


def test_invalid_unknown_field_policy_raises():
    raw = [{"id": "doc-1", "text": "hello", "metadata": {}}]
    with pytest.raises(ValueError):
        ingest_raw_records(raw, LEGAL_SCHEMA, unknown_field_policy="bogus")


# ---------------------------------------------------------------------------
# Integration: ingestion output feeds InlineEmbeddingProvider directly
# ---------------------------------------------------------------------------


def test_ingested_documents_feed_inline_embedding_provider_directly():
    raw = [
        {"id": "doc-1", "text": "a", "metadata": {"doctype": "dahir"}},
        {"id": "doc-2", "text": "b", "metadata": {"doctype": "marsoum"}},
    ]
    embeddings = {"doc-1": _emb([0.1, 0.2]), "doc-2": _emb([0.3, 0.4])}
    report = ingest_raw_records(raw, LEGAL_SCHEMA, embeddings=embeddings)

    provider = InlineEmbeddingProvider(report.valid_documents)
    assert provider.get_embedding("doc-1").vector == [0.1, 0.2]
    assert provider.get_embedding("doc-2").vector == [0.3, 0.4]
    assert provider.get_embedding_dimension() == 2