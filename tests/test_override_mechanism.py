"""
tests/test_override_mechanism.py

The scenario: a project declares `title` as an `equality` filter over a
STRING field -- the generic `EqualityFilter` would require an exact
(case-sensitive) match. This project's custom layer needs
case-INSENSITIVE equality for that one field instead (e.g. because
titles are inconsistently cased in the source data), without changing
what "equality" means for every OTHER field in the project, and without
touching `app/core/filtering/filters.py` at all.

This is deliberately a different scenario from the fuzzy-title
filter (a NEW operation, `contains`-like-but-fuzzy) -- this test proves
the narrower, current claim: the SAME declared operation ("equality")
can have its BEHAVIOR overridden for one field, generically, via
`custom_filters`, while every other field with that same operation keeps
using the generic implementation untouched.
"""
from __future__ import annotations

import pytest

from app.core.config.loader import ConfigLoadError
from app.core.filtering import EqualityFilter, FilterError, load_filters
from app.core.filtering.base import Filter
from app.core.filtering.registry import register_filter
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument


# ---------------------------------------------------------------------------
# The custom override: case-insensitive equality, for exactly one field.
#
# Deliberately NOT decorated with @register_filter("equality") -- doing so
# would try to register a SECOND class under the operation name
# "equality", which registry.py's own docstring calls out as exactly the
# kind of silent conflict that must fail loudly at import time. A
# per-field override is a call-site concern (passed into
# `custom_filters`), never a global registry entry.
# ---------------------------------------------------------------------------
class CaseInsensitiveEqualityFilter(Filter):
    operation = "equality"  # must match the field's declared operation

    def apply(self, records, field, params):
        if params is None:
            return list(records)
        values = params if isinstance(params, (list, tuple, set)) else [params]
        if not values:
            return list(records)

        targets = {str(v).casefold() for v in values}
        return [
            r
            for r in records
            if r.metadata.get(field) is not None and str(r.metadata[field]).casefold() in targets
        ]


_CONFIG_YAML = """
schema_version: 1
filters:
  title:
    type: string
    operation: equality
  document_type:
    type: string
    operation: equality
search: {}
frontend:
  branding:
    title: "Override Demo"
"""

_RECORDS = [
    NormalizedDocument(
        id="doc-1", text="...", metadata={"title": "Al-Tabaqat Al-Kubra", "document_type": "Book"}
    ),
    NormalizedDocument(
        id="doc-2", text="...", metadata={"title": "al-tabaqat al-kubra", "document_type": "book"}
    ),
    NormalizedDocument(
        id="doc-3", text="...", metadata={"title": "Something Else", "document_type": "Decree"}
    ),
]


@pytest.fixture()
def config_and_filters(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_CONFIG_YAML)
    return load_filters(config_path, custom_filters={"title": CaseInsensitiveEqualityFilter})


def test_overridden_field_uses_custom_class(config_and_filters):
    _, filters = config_and_filters
    assert isinstance(filters["title"], CaseInsensitiveEqualityFilter)


def test_non_overridden_field_still_uses_generic_class(config_and_filters):
    """The override is per-field -- 'document_type' also uses 'equality'
    but was NOT named in custom_filters, so it must still be the generic
    EqualityFilter, untouched by the override applied to 'title'."""
    _, filters = config_and_filters
    assert isinstance(filters["document_type"], EqualityFilter)
    assert not isinstance(filters["document_type"], CaseInsensitiveEqualityFilter)


def test_override_actually_changes_behavior_end_to_end(config_and_filters):
    """The whole point of the seam: querying 'title' now matches
    case-insensitively, where the generic EqualityFilter would not."""
    _, filters = config_and_filters

    result = filters["title"].apply(_RECORDS, "title", "AL-TABAQAT AL-KUBRA")
    assert {r.id for r in result} == {"doc-1", "doc-2"}


def test_generic_field_keeps_exact_match_semantics(config_and_filters):
    """Sanity check that the override didn't leak into the generic
    EqualityFilter's own behavior for the non-overridden field."""
    _, filters = config_and_filters

    result = filters["document_type"].apply(_RECORDS, "document_type", "Book")
    assert {r.id for r in result} == {"doc-1"}  # "book" (doc-2) does NOT match, case-sensitive


def test_override_declaring_wrong_operation_is_rejected(tmp_path):
    """An override class whose own `operation` doesn't match what the
    field is configured as must be rejected at load time (config +
    runtime behavior must never silently disagree about what operation a
    field exposes) -- see config_loader.py's own docstring."""

    class WrongOperationOverride(Filter):
        operation = "contains"  # field below is declared as "equality"

        def apply(self, records, field, params):  # pragma: no cover - never reached
            return list(records)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(_CONFIG_YAML)

    with pytest.raises(ConfigLoadError, match="operation"):
        load_filters(config_path, custom_filters={"title": WrongOperationOverride})


def test_override_naming_an_undeclared_field_is_rejected(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_CONFIG_YAML)

    with pytest.raises(ConfigLoadError, match="not declared"):
        load_filters(
            config_path, custom_filters={"nonexistent_field": CaseInsensitiveEqualityFilter}
        )


def test_override_still_enforces_type_operation_compatibility(tmp_path):
    """An override cannot bypass Filter.__init__'s own field_type/operation
    compatibility check merely by being an override -- e.g. 'contains' is
    still not valid on a bool field, custom class or not."""

    class CustomContains(Filter):
        operation = "contains"

        def apply(self, records, field, params):  # pragma: no cover - never reached
            return list(records)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 1
filters:
  flagged:
    type: bool
    operation: equality
search: {}
frontend:
  branding:
    title: "Override Demo"
"""
    )

    # The field is declared as "equality"; the override declares
    # "contains" -- rejected because the OVERRIDE'S operation disagrees
    # with the field's configured operation (independent of the
    # bool/contains incompatibility, which would ALSO reject it).
    with pytest.raises(ConfigLoadError, match="operation"):
        load_filters(config_path, custom_filters={"flagged": CustomContains})
