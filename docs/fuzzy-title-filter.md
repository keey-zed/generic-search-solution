# Fuzzy Title Filter (Phase 3, item 2)

This document specifies **Phase 3, item 2**: "one real example custom
filter — fuzzy title matching — as the reference implementation of 'how
to build a custom filter correctly.'"

**Correction note**: an earlier version of this deliverable lived under
`app/custom/legal/`, motivated by a plausible-but-invented "OCR'd legal
titles" scenario. Once the actual source document became available to
check against, it turned out §4 already gives an exact, specific
example — a **book** search application, not legal — and §11's
architecture diagram confirms it (`Book Search → Fuzzy title`, while
`Legal Search` shows only generic, unspecified `Custom filters`). This
was moved to `app/custom/books/` to match.

```bash
PYTHONPATH=. python3 -m pytest tests/test_fuzzy_title_filter.py
```

## §4, quoted directly

> Suppose we are searching a database of books and the user does not
> know the exact title. They may search for something close to *Al-Tabaqat
> al-Kubra*, but the actual title stored in the database may differ
> slightly in spelling or transliteration. In this case, we may want a
> fuzzy matching filter that tolerates minor spelling differences.
>
> Initially, such functionality could be implemented as a custom
> operation for the books application. If we later realize that fuzzy
> matching is useful across many applications, we can promote it into
> the generic core.

`app/custom/books/raw_loader.py`'s sample catalog reproduces this
scenario exactly: Ibn Sa'd's classical biographical dictionary is
stored as `"Kitab al-Tabaqat al-Kabir"`; a user searching for the more
commonly known transliteration `"Al-Tabaqat al-Kubra"` should still find
it.

## Why the generic filter isn't enough

`app/custom/books/config.yaml` declares:

```yaml
title:
  type: string
  operation: contains
```

The generic `ContainsFilter` does exact, case-insensitive substring
search. A transliterated title has no single "correct" spelling —
`"al-Tabaqat"` vs. `"al-Tabakat"` vs. `"al-Ṭabaqāt"`, `"al-Kubra"` vs.
`"al-Kabir"` are all reasonable renderings a user might type — so exact
substring search silently returns nothing whenever the typed spelling
isn't the one stored. `FuzzyTitleContainsFilter`
(`app/custom/books/fuzzy_title_filter.py`) tolerates that variance
instead of requiring a byte-perfect match.

Proven, not just asserted:

```python
# Generic filter, given the exact §4 query, finds nothing:
ContainsFilter(field_type=STRING).apply(records, "title", "Al-Tabaqat al-Kubra")
# -> []   (record's title is "Kitab al-Tabaqat al-Kabir")

# The fuzzy override finds it:
FuzzyTitleContainsFilter(field_type=STRING).apply(records, "title", "Al-Tabaqat al-Kubra")
# -> [book-1]
```

## How it works

1. **Normalize** both the query and each candidate field value: strip
   diacritics (`unicodedata` NFD decomposition + drop combining marks)
   and case-fold. `"al-Ṭabaqāt"`, `"al-tabaqat"`, and `"AL-TABAQAT"` all
   compare equal.
2. **Slide a window** the length of the (normalized) query across the
   (normalized) field value, computing `difflib.SequenceMatcher`'s
   similarity ratio for each window.
3. **Match if the best window's ratio ≥ `threshold`** (default `0.82`).
   An exact substring always produces a ratio-1.0 window, so this filter
   is a strict superset of exact substring matching — nothing that
   matched before stops matching.
4. Multiple query values are OR'd (same convention as every generic
   filter): matches if *any* value is fuzzy-found.

`threshold` only accepts `(0.0, 1.0]`. It's fixed as a constructor
keyword with a default rather than something `config.yaml` can set,
because `CustomFilterMap` only threads `field_type`/`item_type` through
construction (see `app/api/orchestrator.py` /
`app/core/filtering/config_loader.py`) — a project needing a different
default should subclass with a different `threshold` default, not expect
config.yaml to parameterize it in v0.

**Known limitation, stated plainly**: the sliding-window scan is
`O(len(haystack) * len(needle))` per candidate value. Fine for a title
field on this project's current corpus size; not the implementation to
reach for on a much longer text field or much larger corpus without
checking it's still fast enough first. This is a correctness-first
reference implementation, not a performance-tuned one.

## The "how to build a custom filter correctly" lessons this models

1. **Depend only on the public surface of `app.core`** — `Filter`,
   `FilterError`, `MetadataFieldType` — never on private helpers like
   `app.core.filtering.base._as_list`. This file re-implements the small
   bit of param-normalization it needs rather than reaching into core
   internals, on purpose: custom code coupling itself to core internals
   is exactly the kind of drift the "repo copy" model can't detect until
   it silently breaks after an unrelated core refactor.
2. **Declare `operation = "contains"`** — matching exactly what
   `config.yaml` declares for the `title` field. Fuzzy matching is a
   different *implementation* of "contains", never a different
   *operation* (see `docs/override-mechanism.md`).
3. **Follow the same conventions every generic filter follows**
   (`docs/filtering.md` §2): empty/`None` params is a no-op, a missing
   field value never matches, never mutate the input list, raise
   `FilterError` — never a bare exception — for malformed construction
   arguments.
4. **Add a narrower safety net where the class needs one.**
   `Filter.__init__`'s own compatibility check would allow this
   operation on a `LIST` field (generic `contains` supports both STRING
   and LIST) — `FuzzyTitleContainsFilter.__init__` additionally rejects
   `LIST` itself, since fuzzy-matching individual list items isn't
   implemented here, and says so clearly rather than behaving
   unpredictably.

## The promotion-rule preview, in §4's own words

> "If we later realize that fuzzy matching is useful across many
> applications, we can promote it into the generic core."

This filter is books-specific *for now*. If a second project
independently needs approximate text matching, that repetition is the
signal to promote a generalized version into
`app/core/filtering/filters.py` as a new built-in operation — not to
have each project reinvent it in its own custom layer. The full rule
(Phase 3, item 3) isn't written yet; this is the one concrete example it
will eventually reference.

## What's deliberately not built here

- **Configurable threshold via `config.yaml`.** See the `threshold`
  section above — v0's `CustomFilterMap` contract doesn't support it.
- **Fuzzy matching over `LIST` fields.** Explicitly rejected at
  construction, not silently unsupported.
- **The custom-vs-generic promotion doc itself.** Phase 3, item 3.