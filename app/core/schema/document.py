"""
app/core/schema/document.py

The single standard input format every project's ingestion pipeline must
produce (source doc §7), and the ONLY document shape the generic core is
allowed to import or depend on.

Design principle: this is a "wire format" model. It only knows that
metadata values are JSON-safe scalars or flat lists of scalars — it does
NOT know what any field means or what type it "should" be. That knowledge
lives one layer up, in metadata_types.py, driven by each project's YAML
config. This split is what lets core/ stay genuinely use-case-agnostic:
DocumentRecord never changes no matter how many projects fork this repo.

Explicit non-goals (do not "fix" these here — see docs/metadata-typing.md
"Deferred / explicitly out of scope" for the reasoning):
  - No nested objects in metadata (flat key -> scalar | list[scalar] only).
  - No embeddings field here — a DocumentRecord is text + metadata only.
  - No per-field typing at this level — that's metadata_types.py's job.
"""
from __future__ import annotations

from typing import Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A metadata value as it exists on the wire (raw JSON), before any
# project-specific typing is applied. JSON has no native date/datetime
# type, so dates always arrive here as strings (see metadata_types.py for
# the accepted string format).
JSONScalar = Union[str, int, float, bool, None]

# A metadata field is either a single scalar or a flat, homogeneous-enough
# list of scalars (homogeneity is enforced later, by metadata_types.py,
# against the declared field type — not here, because core/document.py
# must not need to know what "homogeneous" means for a given field).
MetadataValue = Union[JSONScalar, list[JSONScalar]]


class DocumentRecord(BaseModel):
    """
    The standard record shape passed between ingestion and the generic
    core. Every project's ingestion pipeline (custom layer) must produce
    a list of these, or something that validates as one, before anything
    in core/ touches the data.
    """

    # extra="forbid": an ingestion bug that accidentally adds a stray
    # top-level key (e.g. a leftover `embedding` field bolted on ad hoc)
    # must fail loudly at validation time, not silently pass through and
    # surprise someone three modules downstream.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: str = Field(
        ...,
        min_length=1,
        description=(
            "Unique identifier for this record within its corpus. "
            "Uniqueness is enforced across a batch by validate_document_batch() "
            "in metadata_types.py, not by this model in isolation (a single "
            "record can't know about its siblings)."
        ),
    )
    text: str = Field(
        ...,
        description=(
            "Searchable textual content. Empty string is allowed (e.g. a "
            "record that exists for metadata/filtering purposes only) — "
            "but the field must be present; use '' explicitly, never omit it."
        ),
    )
    metadata: dict[str, MetadataValue] = Field(
        default_factory=dict,
        description=(
            "Flat key -> scalar | list[scalar] map. No nested objects. "
            "Values are untyped JSON scalars at this level; project-declared "
            "typing and validation happens in metadata_types.py."
        ),
    )

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must not be blank or whitespace-only")
        return v

    @field_validator("metadata")
    @classmethod
    def metadata_values_must_be_flat(
        cls, v: dict[str, MetadataValue]
    ) -> dict[str, MetadataValue]:
        for key, value in v.items():
            if not key or not key.strip():
                raise ValueError("metadata keys must not be blank")
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, list):
                        raise ValueError(
                            f"metadata['{key}']: nested lists are not allowed "
                            "(flat list of scalars only)"
                        )
                    if isinstance(item, dict):
                        raise ValueError(
                            f"metadata['{key}']: list items must be scalars, "
                            "not objects"
                        )
            elif isinstance(value, dict):
                raise ValueError(
                    f"metadata['{key}']: nested objects are not allowed "
                    "in v0 of the standard schema (flat metadata only)"
                )
        return v


def document_record_json_schema() -> dict:
    """Regenerate the canonical JSON Schema from this model.

    Kept as a function (rather than only a static .json file) so the
    checked-in document.schema.json can be regenerated and diffed whenever
    this model changes, instead of drifting silently out of sync.
    """
    return DocumentRecord.model_json_schema()
