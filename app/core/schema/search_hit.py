"""
app/core/schema/search_hit.py

The generic shape of one retrieval result, produced immediately after
retrieval and before ranking/pagination touch it:

    Documents -> Retrieval -> List[SearchHit] -> Ranking -> Pagination -> API

Retrieval vs ranking vs pagination, briefly (so it's clear what does NOT
belong on SearchHit):

  - Retrieval decides WHICH documents match a query at all, and produces
    one SearchHit per match, in no particular guaranteed order.
  - Ranking takes that List[SearchHit] and decides ORDER (and may use or
    recompute `score` to do it) -- it does not change what a SearchHit
    contains.
  - Pagination takes an ordered List[SearchHit] and decides which SLICE
    of it a given request/page sees. Page number, page size, and offset
    are properties of a *request*, not of an individual result -- so
    none of that belongs on SearchHit. If a future need arises to expose
    a hit's position, it lives in a page/response wrapper model, never
    on SearchHit itself.

This module builds on two things that already exist rather than
inventing new representations:

  - `matched_fields` is generic, drawn from DocumentRecord's own
    vocabulary ("text" for the main content field, or a metadata key
    name) -- never a domain-specific name like "matched_legal_type" (see
    field docstring below).
  - `metadata` reuses metadata_types.py's typed metadata shape
    (dict[str, TypedMetadataValue]), the same shape every
    NormalizedDocument already carries. SearchHit does not define its
    own metadata representation.
  - `snippet` generalizes the (chunk text + source_ranges) pairing
    already used by the legacy lexical/semantic search code in
    app/routes.py (`_sanitize_source_ranges`, `_build_item`) into a
    reusable, validated model, without hardcoding "chunk" as a
    legal-corpus-specific concept.
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schema.metadata_types import TypedMetadataValue


class Snippet(BaseModel):
    """A short piece of matched text plus where the match(es) are within
    it, so a UI can show *why* a hit matched (highlighting) -- generic
    across any text field of any document type.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="The snippet text to show the user.")
    highlight_ranges: list[tuple[int, int]] = Field(
        default_factory=list,
        description=(
            "Half-open [start, end) character offsets into `text` "
            "identifying matched substrings, for highlighting. Empty "
            "when a match can't be localized to a substring (e.g. a "
            "pure semantic/vector match with no exact span)."
        ),
    )

    @field_validator("highlight_ranges")
    @classmethod
    def ranges_must_be_valid(cls, v: list[tuple[int, int]], info):
        text = info.data.get("text", "") or ""
        text_len = len(text)
        for start, end in v:
            if start < 0 or end < 0:
                raise ValueError(f"highlight range ({start}, {end}) must not be negative")
            if end <= start:
                raise ValueError(f"highlight range ({start}, {end}) must have end > start")
            if end > text_len:
                raise ValueError(
                    f"highlight range ({start}, {end}) exceeds snippet text length ({text_len})"
                )
        return v


class SearchHit(BaseModel):
    """One retrieval result, before ranking or pagination are applied.

    Deliberately does NOT contain: rank/position, page number, or any
    other ordering/paging concern -- see module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        min_length=1,
        description="Matches the source DocumentRecord.id this hit refers to.",
    )
    score: Optional[float] = Field(
        default=None,
        description=(
            "Retrieval-stage relevance score, if the retrieval strategy "
            "that produced this hit has one (e.g. semantic similarity, "
            "BM25). None when the strategy has no notion of a score at "
            "all (e.g. boolean lexical matching, a pure metadata filter) "
            "-- None means 'not applicable', never a stand-in for zero "
            "relevance."
        ),
    )
    matched_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the fields that matched the query: 'text' for the "
            "main content field, or a metadata key such as 'author' or "
            "'doctype'. Always drawn from the project's own declared "
            "field names -- never a domain-specific label like "
            "'matched_legal_type'. A UI may localize/relabel these "
            "per-project; the schema itself stays domain-agnostic."
        ),
    )
    snippet: Optional[Snippet] = Field(
        default=None,
        description=(
            "Matched text plus highlight ranges, if applicable. None "
            "for a hit that matched purely on metadata, with nothing "
            "meaningful to highlight in the text."
        ),
    )
    metadata: dict[str, TypedMetadataValue] = Field(
        default_factory=dict,
        description=(
            "This document's typed metadata, in exactly the shape "
            "produced by metadata_types.normalize_metadata() / "
            "NormalizedDocument.metadata -- SearchHit reuses that "
            "representation rather than defining its own."
        ),
    )

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must not be blank or whitespace-only")
        return v

    @field_validator("score")
    @classmethod
    def score_must_be_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (math.isnan(v) or math.isinf(v)):
            raise ValueError("score must be a finite number, not NaN/Inf")
        return v

    @field_validator("matched_fields")
    @classmethod
    def matched_fields_must_not_contain_blanks(cls, v: list[str]) -> list[str]:
        for name in v:
            if not name or not name.strip():
                raise ValueError("matched_fields entries must not be blank")
        return v