import pytest
from pydantic import ValidationError

from app.core.schema.document import DocumentRecord


def test_minimal_valid_record():
    r = DocumentRecord(id="doc-1", text="hello world", metadata={})
    assert r.id == "doc-1"
    assert r.metadata == {}


def test_empty_text_is_allowed():
    r = DocumentRecord(id="doc-1", text="", metadata={})
    assert r.text == ""


def test_missing_text_field_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", metadata={})


def test_missing_id_field_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(text="hello", metadata={})


def test_blank_id_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="   ", text="hello", metadata={})


def test_empty_string_id_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="", text="hello", metadata={})


def test_metadata_defaults_to_empty_dict():
    r = DocumentRecord(id="doc-1", text="hello")
    assert r.metadata == {}


def test_metadata_flat_scalars_allowed():
    r = DocumentRecord(
        id="doc-1",
        text="hello",
        metadata={"a": "x", "b": 1, "c": 1.5, "d": True, "e": None},
    )
    assert r.metadata["a"] == "x"
    assert r.metadata["d"] is True


def test_metadata_flat_list_of_scalars_allowed():
    r = DocumentRecord(id="doc-1", text="hello", metadata={"tags": ["a", "b", "c"]})
    assert r.metadata["tags"] == ["a", "b", "c"]


def test_metadata_empty_list_allowed():
    r = DocumentRecord(id="doc-1", text="hello", metadata={"tags": []})
    assert r.metadata["tags"] == []


def test_metadata_nested_object_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={"a": {"nested": "no"}})


def test_metadata_nested_list_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={"a": [["nested"], ["no"]]})


def test_metadata_list_of_objects_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={"a": [{"x": 1}]})


def test_metadata_blank_key_rejected():
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={"": "value"})


def test_unknown_top_level_field_rejected():
    """extra='forbid' — a stray top-level key (e.g. leftover `embedding`)
    must fail loudly at validation, not pass through silently."""
    with pytest.raises(ValidationError):
        DocumentRecord(id="doc-1", text="hello", metadata={}, embedding=[0.1, 0.2])


def test_round_trip_json():
    r = DocumentRecord(id="doc-1", text="hello", metadata={"a": "x", "n": 3})
    dumped = r.model_dump_json()
    r2 = DocumentRecord.model_validate_json(dumped)
    assert r == r2


def test_json_schema_generation_does_not_error():
    schema = DocumentRecord.model_json_schema()
    assert schema["title"] == "DocumentRecord"
    assert "id" in schema["properties"]
    assert "text" in schema["properties"]
    assert "metadata" in schema["properties"]
