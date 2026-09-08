# Override Mechanism How-To

This document is part of **Phase 6, item 4** (full documentation pass:
"override mechanism how-to"). It also fixes a dangling reference: several
files (`docs/custom-vs-generic.md`, `docs/fuzzy-title-filter.md`,
`docs/custom-layer-template.md`, `app/custom/legal/case_insensitive_equality_filter.py`)
already pointed here for the mechanics; this document didn't exist yet
until now.

```bash
PYTHONPATH=. python3 -m pytest tests/test_override_mechanism.py
```

## The chain (source doc §6)

> generic default → use-case configuration → optional custom override

Concretely, in `build_filters_from_config()`
(`app/core/filtering/config_loader.py`), for every field declared in
`config.yaml`:

1. **Generic default** — look the field's declared `operation` up in
   the global operation registry (`app/core/filtering/registry.py`,
   Phase 1) to get the built-in `Filter` class (`EqualityFilter` /
   `RangeFilter` / `ContainsFilter`).
2. **Use-case configuration** — `config.yaml` is what decided the
   field's `type` and `operation` in the first place; that's the input
   to step 1.
3. **Optional custom override** — if the caller passed a
   `custom_filters` mapping (`CustomFilterMap = Mapping[str, Type[Filter]]`)
   naming this field, that class is used **instead of** whatever step 1
   would have resolved to.

## How to actually override a field

```python
from app.core.filtering import Filter

class AccentInsensitiveEqualityFilter(Filter):
    operation = "equality"   # MUST match the field's operation in config.yaml

    def apply(self, records, field, params):
        ...  # custom matching logic

# Wired in via a project's custom_filters.py (see app/custom/_template/):
CUSTOM_FILTERS = {"author_name": AccentInsensitiveEqualityFilter}
```

```python
from app.core.filtering import load_filters
# or, more commonly, through a project's own bootstrap.build_search_engine()

config, filters = load_filters("config.yaml", custom_filters=CUSTOM_FILTERS)
type(filters["author_name"])  # -> AccentInsensitiveEqualityFilter, not EqualityFilter
```

A field with no entry in `custom_filters` resolves generically, exactly
as in Phase 1 — overriding is opt-in per field, never a project-wide
switch.

## Two registries, not one — and why

| | Generic registry (`registry.py`) | `custom_filters` mapping (per call, per project) |
|---|---|---|
| Keyed by | operation name (`"equality"`) | field name (`"author_name"`) |
| Scope | every project, every field using that operation | one project, one field, one `build_filters_from_config()` call |
| Where it lives | global, process-wide | a plain dict a project's `custom_filters.py` builds and passes in explicitly — **not** a global registry |

This is deliberate, and different from how the generic operation
registry works: `custom_filters` is passed as an explicit argument
(`build_filters_from_config(config, custom_filters=...)` /
`load_filters(path, custom_filters=...)`), not registered into shared
global state. That means two different project copies can override the
exact same field name completely differently without any risk of
stepping on each other — there's no shared mutable registry for them to
collide in.

## The one extra safety check overrides get

An override class still goes through `Filter.__init__`'s own
field_type/operation compatibility check (`app/core/filtering/base.py`)
— being an override does not exempt a class from "contains is not valid
on a bool field." On top of that, `build_filters_from_config()` checks
one more thing specific to overrides: **the override's declared
`operation` must match what the field's `config.yaml` entry declares**.

```
custom_filters['title'] = FuzzyTitleContainsFilter declares operation 'contains',
but filters['title'].operation in config is 'equality' -- an override must
implement the SAME operation the config declares for that field.
```

This exists because an override changes **how** an operation behaves
for one field, never **which** operation that field exposes — allowing
them to silently disagree would mean the config and the runtime
behavior disagree about what kind of filter a field even is. See
`docs/custom-vs-generic.md` for when writing an override is the right
call in the first place, versus using a generic filter as-is.

## Real examples in this codebase

- `app/custom/books/fuzzy_title_filter.py` — overrides `title`'s
  `contains` operation with fuzzy/approximate matching. See
  `docs/fuzzy-title-filter.md`.
- `app/custom/legal/case_insensitive_equality_filter.py` — overrides
  `document_type`'s `equality` operation with case-insensitive
  matching. This is also the literal proof for Phase 3's Definition of
  Done ("a new filter can be added by a third developer, following only
  the template and doc, without reading core source code").

Both keep their project's `custom_filters.py` as the single place the
override is wired in — see `app/custom/_template/custom_filters.py` for
the registration pattern a new project copies.

## What's deliberately not built here

- **An override that changes which operation a field exposes.** Not
  possible by design (see the safety check above) — this is the
  boundary between "override" and "the field is configured wrong."
- **A global/shared custom filter registry.** Deliberately avoided —
  see "Two registries, not one" above.
- **Config-driven override selection** (e.g. a YAML key naming which
  Python class to import). `custom_filters` is passed in Python code at
  startup, not declared in `config.yaml` itself — keeping "what filters
  exist" (config) separate from "which Python classes implement them"
  (code) intentionally.