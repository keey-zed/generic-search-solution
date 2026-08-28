"""
app/core/ingestion/loader.py

Phase 1, Track B, Task 1: the ingestion/normalization layer.

This is the ONE place raw project data becomes the standard shape the
rest of core is allowed to depend on. Deliberately thin -- actual
project-specific extraction (parsing a legal-text XML dump, scraping a
books CSV, whatever a given project's raw data looks like) belongs in
that project's app/custom/<project>/ layer, producing plain dicts shaped
like {"id": ..., "text": ..., "metadata": {...}} before this module ever
sees them. What belongs here, and only here, is:

  - validating that shape (delegates to DocumentRecord, Phase 0)
  - normalizing/typing metadata against the project's declared schema
    (delegates to metadata_types.normalize_metadata /
    validate_document_batch, Phase 0 -- this module does not
    reimplement type coercion, it calls the single existing
    implementation)
  - attaching a precomputed embedding by id, if one was supplied
    (delegates to the Embedding shape, Phase 0 deliverable 2)
  - collecting every problem across the whole batch with a clear,
    per-record message -- never crashing on the first bad record, and
    never letting a record that failed any check leak into the valid
    output

    Raw project data (dicts)   +   embeddings: dict[id, Embedding]
                |
                v
        ingest_raw_records()
                |
    --------------------------------
    |                              |
    v                              v
List[IngestedDocument]      IngestionReport (errors, duplicates, unmatched embeddings)

IngestedDocument is duck-type compatible with what
`InlineEmbeddingProvider` (app/core/embeddings/provider.py) expects --
it has `.id` and `.embedding` -- so
`InlineEmbeddingProvider(report.valid_documents)` works directly with no
conversion step.

Two failure levels are deliberately kept distinct, because they mean
different things to whoever is debugging a bad ingestion run:

  1. "wire_format" errors -- DocumentRecord rejects the raw record
     outright (missing id/text, nested metadata, blank id, extra keys,
     ...). The record is structurally broken, independent of any
     project's schema.
  2. "metadata_typing" errors -- normalize_metadata() rejects a field's
     *value* against the project's declared schema (wrong type, a
     required field missing, ...). The record's shape is fine, its
     content doesn't match what this project declared.

Both stages report through the same FieldError shape (field, message,
raw_value_repr) so a caller only has to handle one error format, while
`stage` on each RecordIngestionError still says which check produced it.
"""
from __future__ import annotations

from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.schema.document import DocumentRecord
from app.core.schema.embedding import Embedding
from app.core.schema.metadata_types import (
    FieldError,
    MetadataSchema,
    NormalizedDocument,
    RecordErrors,
    validate_document_batch,
)


class IngestedDocument(NormalizedDocument):
    """The standard output shape of ingestion: typed metadata (Layer 1,
    same shape as NormalizedDocument) plus an optional embedding.

    `embedding` defaults to None, same reasoning as
    EmbeddedDocumentRecord (app/core/schema/embedding.py): a document
    ingested before its embedding job has run, or one from a project
    that hasn't adopted embeddings at all yet, is a normal, representable
    state -- not an error.
    """

    embedding: Optional[Embedding] = None


class RecordIngestionError(RecordErrors):
    """A RecordErrors (Phase 0's existing per-record error shape) tagged
    with which ingestion stage produced it, so a caller/log message can
    tell "this record is structurally broken" apart from "this record's
    content doesn't match the schema" without inspecting message text."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal["wire_format", "metadata_typing"]


class IngestionReport(BaseModel):
    """Full result of one ingest_raw_records() call. Never partial --
    every input record ends up in exactly one of valid_documents,
    record_errors, or duplicate_ids (never more than one)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    valid_documents: list[IngestedDocument]
    record_errors: list[RecordIngestionError]
    duplicate_ids: list[str]
    unmatched_embedding_ids: list[str] = Field(
        default_factory=list,
        description=(
            "ids present in the `embeddings` argument that were never "
            "attached to any valid document -- because no record with "
            "that id was supplied, or because the record with that id "
            "failed validation. Not an error by itself, but almost "
            "always signals an id mismatch between a project's raw data "
            "and its embeddings, worth surfacing rather than silently "
            "dropping."
        ),
    )

    @property
    def is_clean(self) -> bool:
        return not self.record_errors and not self.duplicate_ids

    @property
    def summary(self) -> str:
        parts = [
            f"{len(self.valid_documents)} valid",
            f"{len(self.record_errors)} record(s) with errors",
            f"{len(self.duplicate_ids)} duplicate id(s)",
        ]
        if self.unmatched_embedding_ids:
            parts.append(f"{len(self.unmatched_embedding_ids)} unmatched embedding(s)")
        return ", ".join(parts)


def _record_label(raw: Any, index: int) -> str:
    """Best-effort id for an error message. A record can fail validation
    precisely because its id is missing/blank/wrong-type, so error
    reporting can't always assume a usable id exists -- fall back to a
    positional label instead of crashing while trying to report an
    error."""
    if isinstance(raw, dict):
        candidate = raw.get("id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return f"<record at index {index}>"


def _field_errors_from_validation_error(exc: ValidationError) -> list[FieldError]:
    """Convert a Pydantic ValidationError (from DocumentRecord) into the
    same FieldError shape normalize_metadata() already uses, so both
    ingestion stages report through one format."""
    out: list[FieldError] = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "<record>"
        out.append(
            FieldError(
                field=field,
                message=err["msg"],
                raw_value_repr=repr(err.get("input")),
            )
        )
    return out


def ingest_raw_records(
    raw_records: Iterable[Any],
    schema: MetadataSchema,
    *,
    embeddings: Optional[dict[str, Embedding]] = None,
    unknown_field_policy: str = "passthrough",
) -> IngestionReport:
    """Validate, normalize, and (optionally) attach embeddings to a batch
    of raw project records, producing the standard ingestion output.

    Args:
        raw_records: an iterable of raw records as produced by a
            project's custom extraction step. Each item is expected to
            be a dict shaped like DocumentRecord ({"id", "text",
            "metadata"}) -- anything else (wrong type, missing keys,
            malformed metadata) is reported as a wire_format error for
            that record, not raised.
        schema: this project's declared MetadataSchema (e.g.
            `UseCaseConfig.to_metadata_schema()` from
            app/core/config/models.py), used to type-check and coerce
            each record's metadata.
        embeddings: optional {document_id: Embedding} map of precomputed
            embeddings (V1 inline storage, per
            app/core/schema/embedding.py). A document with no entry here
            simply ends up with `embedding=None` -- not an error.
        unknown_field_policy: forwarded to validate_document_batch()
            unchanged ("passthrough" or "strict").

    Returns:
        An IngestionReport. Never raises for bad *data* -- only a
        programmer error in the arguments themselves (e.g. an invalid
        unknown_field_policy) propagates, via validate_document_batch().
    """
    embeddings = embeddings or {}

    wire_valid_records: list[DocumentRecord] = []
    wire_errors: list[RecordIngestionError] = []

    for index, raw in enumerate(raw_records):
        label = _record_label(raw, index)

        if not isinstance(raw, dict):
            wire_errors.append(
                RecordIngestionError(
                    record_id=label,
                    stage="wire_format",
                    errors=[
                        FieldError(
                            field="<record>",
                            message=f"expected a mapping (dict), got {type(raw).__name__}",
                            raw_value_repr=repr(raw),
                        )
                    ],
                )
            )
            continue

        try:
            wire_valid_records.append(DocumentRecord.model_validate(raw))
        except ValidationError as exc:
            wire_errors.append(
                RecordIngestionError(
                    record_id=label,
                    stage="wire_format",
                    errors=_field_errors_from_validation_error(exc),
                )
            )

    # Metadata typing + duplicate-id detection: delegate entirely to the
    # existing Phase 0 implementation, once, on the records that at least
    # passed the wire-format check.
    batch_result = validate_document_batch(
        wire_valid_records, schema, unknown_field_policy=unknown_field_policy
    )

    typing_errors = [
        RecordIngestionError(record_id=re.record_id, stage="metadata_typing", errors=re.errors)
        for re in batch_result.record_errors
    ]

    valid_documents = [
        IngestedDocument(
            id=doc.id,
            text=doc.text,
            metadata=doc.metadata,
            embedding=embeddings.get(doc.id),
        )
        for doc in batch_result.valid_documents
    ]

    matched_ids = {doc.id for doc in valid_documents}
    unmatched_embedding_ids = sorted(set(embeddings.keys()) - matched_ids)

    return IngestionReport(
        valid_documents=valid_documents,
        record_errors=wire_errors + typing_errors,
        duplicate_ids=batch_result.duplicate_ids,
        unmatched_embedding_ids=unmatched_embedding_ids,
    )