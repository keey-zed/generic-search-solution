from datetime import date

import pytest
from pydantic import ValidationError

from app.core.schema.search_hit import SearchHit, Snippet


# ---------------------------------------------------------------------------
# Snippet
# ---------------------------------------------------------------------------


def test_snippet_minimal():
    s = Snippet(text="hello world")
    assert s.highlight_ranges == []


def test_snippet_valid_highlight_range():
    s = Snippet(text="hello world", highlight_ranges=[(0, 5)])
    assert s.highlight_ranges == [(0, 5)]


def test_snippet_multiple_highlight_ranges():
    s = Snippet(text="hello world", highlight_ranges=[(0, 5), (6, 11)])
    assert s.highlight_ranges == [(0, 5), (6, 11)]


def test_snippet_rejects_end_before_start():
    with pytest.raises(ValidationError):
        Snippet(text="hello world", highlight_ranges=[(5, 2)])


def test_snippet_rejects_equal_start_end():
    with pytest.raises(ValidationError):
        Snippet(text="hello world", highlight_ranges=[(3, 3)])


def test_snippet_rejects_negative_start():
    with pytest.raises(ValidationError):
        Snippet(text="hello world", highlight_ranges=[(-1, 3)])


def test_snippet_rejects_out_of_bounds_end():
    with pytest.raises(ValidationError):
        Snippet(text="hello", highlight_ranges=[(0, 100)])


def test_snippet_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        Snippet(text="hello", chunk_id=3)


# ---------------------------------------------------------------------------
# SearchHit
# ---------------------------------------------------------------------------


def test_minimal_valid_hit():
    hit = SearchHit(id="doc-1")
    assert hit.score is None
    assert hit.matched_fields == []
    assert hit.snippet is None
    assert hit.metadata == {}


def test_blank_id_rejected():
    with pytest.raises(ValidationError):
        SearchHit(id="   ")


def test_score_can_be_omitted_for_non_scoring_retrieval():
    hit = SearchHit(id="doc-1", matched_fields=["text"])
    assert hit.score is None


def test_score_accepted_when_present():
    hit = SearchHit(id="doc-1", score=0.87)
    assert hit.score == 0.87


def test_score_rejects_nan():
    with pytest.raises(ValidationError):
        SearchHit(id="doc-1", score=float("nan"))


def test_score_rejects_inf():
    with pytest.raises(ValidationError):
        SearchHit(id="doc-1", score=float("inf"))


def test_matched_fields_generic_names_allowed():
    hit = SearchHit(id="doc-1", matched_fields=["text", "author", "doctype", "genre"])
    assert hit.matched_fields == ["text", "author", "doctype", "genre"]


def test_matched_fields_rejects_blank_entries():
    with pytest.raises(ValidationError):
        SearchHit(id="doc-1", matched_fields=["text", "  "])


def test_snippet_optional_on_hit():
    hit = SearchHit(id="doc-1", snippet=Snippet(text="matched text", highlight_ranges=[(0, 7)]))
    assert hit.snippet.text == "matched text"
    assert hit.snippet.highlight_ranges == [(0, 7)]


def test_hit_without_snippet_for_metadata_only_match():
    hit = SearchHit(id="doc-1", matched_fields=["doctype"], snippet=None)
    assert hit.snippet is None


def test_metadata_reuses_typed_metadata_shape():
    """metadata must accept the same typed shapes normalize_metadata()
    produces: strings, dates, ints, floats, bools, lists, and None."""
    hit = SearchHit(
        id="doc-1",
        metadata={
            "doctype": "dahir",
            "promulgation_date": date(2018, 8, 16),
            "page_count": 12,
            "confidence": 0.5,
            "is_amended": True,
            "subjects": ["finance", "tax"],
            "signatures": None,
        },
    )
    assert hit.metadata["promulgation_date"] == date(2018, 8, 16)
    assert hit.metadata["subjects"] == ["finance", "tax"]
    assert hit.metadata["signatures"] is None


def test_hit_rejects_unknown_extra_field():
    """Ranking/pagination concerns (rank, page, offset, ...) must not be
    representable on a SearchHit at all."""
    with pytest.raises(ValidationError):
        SearchHit(id="doc-1", rank=1)


def test_hit_rejects_page_field():
    with pytest.raises(ValidationError):
        SearchHit(id="doc-1", page=2)


def test_list_of_hits_is_the_retrieval_output_shape():
    hits: list[SearchHit] = [
        SearchHit(id="doc-1", score=0.9, matched_fields=["text"]),
        SearchHit(id="doc-2", score=None, matched_fields=["doctype"]),
    ]
    assert len(hits) == 2
    assert hits[0].score == 0.9
    assert hits[1].score is None


def test_round_trip_json():
    hit = SearchHit(
        id="doc-1",
        score=0.42,
        matched_fields=["text"],
        snippet=Snippet(text="hello world", highlight_ranges=[(0, 5)]),
        metadata={"doctype": "dahir"},
    )
    dumped = hit.model_dump_json()
    hit2 = SearchHit.model_validate_json(dumped)
    assert hit == hit2


def test_json_schema_generation_does_not_error():
    schema = SearchHit.model_json_schema()
    assert schema["title"] == "SearchHit"
    assert "id" in schema["properties"]
    assert "score" in schema["properties"]
    assert "matched_fields" in schema["properties"]
    assert "snippet" in schema["properties"]
    assert "metadata" in schema["properties"]