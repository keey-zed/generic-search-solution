"""
app/core/schema/embedding.py

Layer 0 extension: the standard shape used to attach a vector embedding
to a document. Deliberately a SEPARATE model from DocumentRecord, not a
field bolted onto it -- DocumentRecord is intentionally "text + metadata
only" (see document.py's module docstring: "No embeddings field here ...
a DocumentRecord is text + metadata only"). Keeping it separate means
DocumentRecord never has to change no matter how many embedding models,
dimensions, or storage backends a project cycles through over time.

`EmbeddedDocumentRecord` below is the V1 storage shape: a DocumentRecord
plus an optional `Embedding`. It exists purely so the V1 inline
implementation (app/core/embeddings/provider.py: InlineEmbeddingProvider)
has something concrete to read from. Retrieval code must NEVER import or
depend on `EmbeddedDocumentRecord` directly -- it goes through
`EmbeddingProvider` instead, so a later switch to a separate embeddings
store or vector DB doesn't touch retrieval code at all. See
app/core/embeddings/provider.py for that interface.
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schema.document import DocumentRecord


class Embedding(BaseModel):
    """A single dense vector embedding plus enough provenance to use it safely.

    Design notes:

    - `model_id` is required, not optional. Vectors produced by two
      different embedding models (or two versions of the same model) are
      not comparable -- mixing them into one similarity computation
      silently produces meaningless scores. This module doesn't enforce
      cross-vector compatibility by itself (a single Embedding has
      nothing to compare against), but it guarantees the tag needed to
      check it is always present. See InlineEmbeddingProvider, which does
      enforce single-model consistency across a batch.
    - Dimensionality is deliberately NOT a separate stored field. A
      `dim` field could desync from the actual vector length (e.g. after
      a manual edit or a buggy loader); exposing it as a computed
      property from `vector` makes that impossible instead of merely
      unlikely.
    """

    model_config = ConfigDict(extra="forbid")

    vector: list[float] = Field(..., min_length=1, description="Dense embedding vector.")
    model_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Identifier of the embedding model/version that produced this "
            "vector, e.g. 'bge-m3', 'text-embedding-3-large@2024-01'. "
            "Required so vectors from incompatible models are never "
            "silently compared against each other."
        ),
    )

    @field_validator("model_id")
    @classmethod
    def model_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model_id must not be blank or whitespace-only")
        return v

    @field_validator("vector")
    @classmethod
    def vector_values_must_be_finite(cls, v: list[float]) -> list[float]:
        for x in v:
            if math.isnan(x) or math.isinf(x):
                raise ValueError("embedding vector must not contain NaN/Inf values")
        return v

    @property
    def dim(self) -> int:
        return len(self.vector)


class EmbeddedDocumentRecord(DocumentRecord):
    """V1 storage shape: a DocumentRecord with its embedding stored inline.

    `embedding` is Optional and defaults to None so that:

      - Documents that haven't been embedded yet (freshly ingested, an
        embedding job hasn't run yet, or a record that's deliberately
        text-only) are representable without inventing a fake/zero
        vector.
      - Backwards compatibility is automatic: any dict/DocumentRecord
        that validated before this field existed still validates here
        unchanged (embedding simply comes out as None). No migration of
        existing data is required to adopt this model.
    """

    embedding: Optional[Embedding] = None