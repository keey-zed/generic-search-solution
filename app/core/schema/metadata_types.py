"""
app/core/schema/metadata_types.py

Layer 1 on top of DocumentRecord (document.py): declares what a project's
metadata fields *mean*, type-wise, and turns raw JSON-safe metadata values
into typed Python values the filtering engine can safely operate on.

This is deliberately a SEPARATE layer from DocumentRecord:
  - DocumentRecord (Layer 0) never changes across projects.
  - MetadataFieldDef / MetadataSchema (Layer 1) is supplied per-project,
    from that project's YAML config (Phase 0 deliverable 4).
  - The filtering engine (Phase 1, Track B) will only ever see the typed
    output of normalize_metadata() / validate_document_batch(), never
    raw DocumentRecord.metadata directly.

Everything here fails LOUD and COLLECTS ALL ERRORS rather than raising on
the first problem. Ingestion of a real corpus is a batch operation — a
developer needs the full list of bad records/fields in one pass, not one
error at a time across ten re-runs.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.schema.document import DocumentRecord, JSONScalar

# ---------------------------------------------------------------------------
# 1. The field type vocabulary
# ---------------------------------------------------------------------------


class MetadataFieldType(str, Enum):
    STRING = "string"
    DATE = "date"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"  # homogeneous flat list; requires item_type

    # Explicitly NOT supported in v0 (documented, not silently missing):
    #   - DATETIME (time-of-day) — add only when a real use case needs it.
    #   - NESTED / OBJECT — see document.py's flat-metadata rule.
    #   - Nested LIST-of-LIST — rejected by MetadataFieldDef validation below.


# Scalar types only (used to validate LIST.item_type — a list's items must
# themselves be one of these, never LIST).
_SCALAR_TYPES = {
    MetadataFieldType.STRING,
    MetadataFieldType.DATE,
    MetadataFieldType.INT,
    MetadataFieldType.FLOAT,
    MetadataFieldType.BOOL,
}

# ISO 8601 date-only format, strictly. Rejects datetimes, slashes,
# non-zero-padded months/days, etc. — one canonical format, no guessing.
_DATE_FORMAT_HINT = "YYYY-MM-DD (ISO 8601 date, no time component)"


class MetadataFieldDef(BaseModel):
    """One declared metadata field, as a project's config would specify it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: MetadataFieldType
    item_type: Optional[MetadataFieldType] = None
    # required=True  -> key must be present in raw metadata AND non-null.
    # required=False -> missing key or JSON null normalizes to None.
    # (Deliberately no separate "nullable" flag — one flag, one meaning,
    #  fewer ways for the two flags to contradict each other.)
    required: bool = False

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field name must not be blank")
        return v

    @model_validator(mode="after")
    def item_type_rules(self) -> "MetadataFieldDef":
        if self.type == MetadataFieldType.LIST:
            if self.item_type is None:
                raise ValueError(
                    f"field '{self.name}': item_type is required when type == LIST"
                )
            if self.item_type not in _SCALAR_TYPES:
                raise ValueError(
                    f"field '{self.name}': item_type must be a scalar type "
                    f"(not LIST) — nested lists are not supported"
                )
        else:
            if self.item_type is not None:
                raise ValueError(
                    f"field '{self.name}': item_type must only be set when type == LIST"
                )
        return self


MetadataSchema = list[MetadataFieldDef]


def _schema_by_name(schema: MetadataSchema) -> dict[str, MetadataFieldDef]:
    by_name: dict[str, MetadataFieldDef] = {}
    for f in schema:
        if f.name in by_name:
            raise ValueError(f"duplicate field name in schema: '{f.name}'")
        by_name[f.name] = f
    return by_name


# ---------------------------------------------------------------------------
# 2. Typed output value
# ---------------------------------------------------------------------------

TypedScalar = Union[str, date, int, float, bool, None]
TypedMetadataValue = Union[TypedScalar, list[TypedScalar]]


# ---------------------------------------------------------------------------
# 3. Per-type coercion rules (this is the part filters ultimately trust)
# ---------------------------------------------------------------------------


class FieldError(BaseModel):
    field: str
    message: str
    raw_value_repr: str


def _coerce_scalar(
    raw: JSONScalar, expected: MetadataFieldType, field_name: str
) -> tuple[Optional[TypedScalar], Optional[str]]:
    """Coerce one raw JSON scalar to the declared type.

    Returns (value, error_message). Exactly one of the two is None.

    Rules (deliberately strict — a strict failure at ingestion time is
    always cheaper to fix than a silently-wrong filter result later):
      STRING -> only `str` accepted. No int/float/bool -> str coercion.
      INT    -> only `int` accepted, and bool is explicitly rejected even
                though Python's `int` and `bool` are related types
                (isinstance(True, int) is True — this is a classic trap
                and is guarded against explicitly below).
      FLOAT  -> `int` or `float` accepted (bool rejected, same trap);
                int is upcast to float.
      BOOL   -> only actual `bool` accepted. No "true"/"false"/1/0
                string or int coercion (locale/ambiguity risk).
      DATE   -> only a `str` matching strict ISO 8601 date format
                (YYYY-MM-DD) is accepted, parsed with a real calendar
                check (e.g. 2024-02-30 is rejected).
    """
    if raw is None:
        return None, None  # caller handles required/optional semantics

    if expected == MetadataFieldType.STRING:
        if isinstance(raw, str):
            return raw, None
        return None, f"expected string, got {type(raw).__name__}: {raw!r}"

    if expected == MetadataFieldType.BOOL:
        if isinstance(raw, bool):
            return raw, None
        return None, f"expected bool, got {type(raw).__name__}: {raw!r}"

    if expected == MetadataFieldType.INT:
        if isinstance(raw, bool):
            return None, f"expected int, got bool: {raw!r}"
        if isinstance(raw, int):
            return raw, None
        return None, (
            f"expected int, got {type(raw).__name__}: {raw!r} "
            "(floats are not auto-truncated to int — fix at the source)"
        )

    if expected == MetadataFieldType.FLOAT:
        if isinstance(raw, bool):
            return None, f"expected float, got bool: {raw!r}"
        if isinstance(raw, (int, float)):
            return float(raw), None
        return None, f"expected float, got {type(raw).__name__}: {raw!r}"

    if expected == MetadataFieldType.DATE:
        if not isinstance(raw, str):
            return None, f"expected date string ({_DATE_FORMAT_HINT}), got {type(raw).__name__}: {raw!r}"
        if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
            return None, f"expected date string in format {_DATE_FORMAT_HINT}, got {raw!r}"
        try:
            return date.fromisoformat(raw), None
        except ValueError as exc:
            return None, f"invalid calendar date {raw!r}: {exc}"

    return None, f"unsupported scalar type: {expected}"


def normalize_metadata(
    record_id: str,
    raw_metadata: dict[str, JSONScalar],
    schema: MetadataSchema,
    *,
    unknown_field_policy: str = "passthrough",
) -> tuple[dict[str, TypedMetadataValue], list[FieldError]]:
    """Normalize one record's raw metadata dict against a declared schema.

    unknown_field_policy:
      "passthrough" (default) — metadata keys not declared in `schema` are
          kept as-is, untyped, in the output. They will simply never be
          usable in a config-declared filter (the config only ever
          references declared field names), but they remain available for
          display purposes. This matches source-doc §9: the engine doesn't
          need to know every field's meaning up front.
      "strict" — any undeclared key raises a FieldError. Use this for
          projects that want to catch typos in raw data (e.g. a metadata
          key that was meant to match a declared field name but doesn't).

    Returns (typed_metadata, errors). typed_metadata always contains one
    key per *declared* field (filled with None when optional-and-missing),
    plus any passthrough keys under "passthrough" policy. Never raises —
    callers decide what to do with a non-empty errors list.
    """
    if unknown_field_policy not in ("passthrough", "strict"):
        raise ValueError(f"unknown_field_policy must be 'passthrough' or 'strict', got {unknown_field_policy!r}")

    by_name = _schema_by_name(schema)
    errors: list[FieldError] = []
    result: dict[str, TypedMetadataValue] = {}

    # 1. Walk declared fields — this guarantees every declared field is a
    #    key in the output, even when absent from the raw record.
    for field_def in schema:
        present = field_def.name in raw_metadata
        raw_value = raw_metadata.get(field_def.name)

        if not present or raw_value is None:
            if field_def.required:
                errors.append(
                    FieldError(
                        field=field_def.name,
                        message="required field is missing or null",
                        raw_value_repr=repr(raw_value),
                    )
                )
                result[field_def.name] = None
            else:
                result[field_def.name] = None
            continue

        if field_def.type == MetadataFieldType.LIST:
            if not isinstance(raw_value, list):
                errors.append(
                    FieldError(
                        field=field_def.name,
                        message=f"expected list, got {type(raw_value).__name__}",
                        raw_value_repr=repr(raw_value),
                    )
                )
                result[field_def.name] = None
                continue

            typed_items: list[TypedScalar] = []
            item_had_error = False
            for idx, item in enumerate(raw_value):
                item_val, item_err = _coerce_scalar(item, field_def.item_type, field_def.name)
                if item_err is not None:
                    errors.append(
                        FieldError(
                            field=f"{field_def.name}[{idx}]",
                            message=item_err,
                            raw_value_repr=repr(item),
                        )
                    )
                    item_had_error = True
                else:
                    typed_items.append(item_val)
            result[field_def.name] = None if item_had_error else typed_items
        else:
            value, err = _coerce_scalar(raw_value, field_def.type, field_def.name)
            if err is not None:
                errors.append(FieldError(field=field_def.name, message=err, raw_value_repr=repr(raw_value)))
                result[field_def.name] = None
            else:
                result[field_def.name] = value

    # 2. Handle keys present in raw metadata but not declared in schema.
    undeclared_keys = set(raw_metadata.keys()) - set(by_name.keys())
    for key in sorted(undeclared_keys):
        if unknown_field_policy == "strict":
            errors.append(
                FieldError(
                    field=key,
                    message="undeclared metadata field (unknown_field_policy='strict')",
                    raw_value_repr=repr(raw_metadata[key]),
                )
            )
        else:
            result[key] = raw_metadata[key]

    return result, errors


# ---------------------------------------------------------------------------
# 4. Batch validation (what ingestion actually calls)
# ---------------------------------------------------------------------------


class NormalizedDocument(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    metadata: dict[str, TypedMetadataValue]


class RecordErrors(BaseModel):
    record_id: str
    errors: list[FieldError]


class BatchValidationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    valid_documents: list[NormalizedDocument]
    record_errors: list[RecordErrors]  # only records with >=1 error
    duplicate_ids: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.record_errors and not self.duplicate_ids

    @property
    def summary(self) -> str:
        return (
            f"{len(self.valid_documents)} valid, "
            f"{len(self.record_errors)} record(s) with errors, "
            f"{len(self.duplicate_ids)} duplicate id(s)"
        )


def validate_document_batch(
    records: list[DocumentRecord],
    schema: MetadataSchema,
    *,
    unknown_field_policy: str = "passthrough",
) -> BatchValidationResult:
    """The one function a project's ingestion pipeline should call.

    - Detects duplicate ids across the whole batch (a single record can't
      know about its siblings, so this can't live in DocumentRecord or in
      normalize_metadata()).
    - A record with ANY field error is excluded from valid_documents and
      reported in record_errors — never partially included, so a filter
      can never silently operate on a half-typed record.
    - Never raises. Always returns a full report so a bulk ingestion run
      surfaces every problem in one pass.
    """
    seen_ids: dict[str, int] = {}
    duplicate_ids: list[str] = []
    valid_documents: list[NormalizedDocument] = []
    record_errors: list[RecordErrors] = []

    for record in records:
        seen_ids[record.id] = seen_ids.get(record.id, 0) + 1

        typed_metadata, errors = normalize_metadata(
            record.id, record.metadata, schema, unknown_field_policy=unknown_field_policy
        )
        if errors:
            record_errors.append(RecordErrors(record_id=record.id, errors=errors))
        else:
            valid_documents.append(
                NormalizedDocument(id=record.id, text=record.text, metadata=typed_metadata)
            )

    duplicate_ids = sorted([rid for rid, count in seen_ids.items() if count > 1])
    if duplicate_ids:
        # Duplicate ids invalidate ALL copies of that id, not just the
        # second occurrence — there is no principled way to pick a
        # "correct" one automatically, so none of them go into
        # valid_documents.
        valid_documents = [d for d in valid_documents if d.id not in duplicate_ids]

    return BatchValidationResult(
        valid_documents=valid_documents,
        record_errors=record_errors,
        duplicate_ids=duplicate_ids,
    )


# ---------------------------------------------------------------------------
# 5. Type -> allowed filter operation compatibility matrix
#
# This is the contract Phase 1 / Track B's YAML config loader uses to
# reject a config that pairs an invalid operation with a field type
# (e.g. `contains` on a BOOL field) at config-load time, per the source
# doc's requirement that bad configs "fail loudly ... not at query time."
#
# v0 only implements the three generic filter kinds from source doc §3
# (range / equality / contains). This matrix is intentionally small and
# explicit — extend it deliberately (and update docs/metadata-typing.md)
# rather than adding operations ad hoc per project.
# ---------------------------------------------------------------------------

FILTER_OPERATION_COMPATIBILITY: dict[MetadataFieldType, set[str]] = {
    MetadataFieldType.STRING: {"equality", "contains"},
    MetadataFieldType.DATE: {"equality", "range"},
    MetadataFieldType.INT: {"equality", "range"},
    MetadataFieldType.FLOAT: {"equality", "range"},
    MetadataFieldType.BOOL: {"equality"},
    # "contains" on LIST means membership: value ∈ list. This is the one
    # place v0 gives a list-typed field a filter meaning at all — richer
    # list operations (e.g. "contains all of", "intersects any of") are
    # explicitly deferred; see docs/metadata-typing.md.
    MetadataFieldType.LIST: {"contains"},
}


def is_operation_compatible(field_type: MetadataFieldType, operation: str) -> bool:
    return operation in FILTER_OPERATION_COMPATIBILITY.get(field_type, set())
