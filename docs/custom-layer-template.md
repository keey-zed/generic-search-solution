# Custom Layer Template

This document specifies **Phase 3, item 1**: the folder structure and
registration pattern a new project uses to add project-specific
filters/behavior without touching `app/core/`.

The actual step-by-step guide lives in
**`app/custom/_template/README.md`**, not here — deliberately, since
that file travels with every copy of the template (per the roadmap's
"repo copy" model: each project is a copy of this codebase, so
instructions need to be *in* the copy, not only in a central docs
folder someone might not carry over). This document is the short
overview + pointer; read the README for the real how-to.

```bash
PYTHONPATH=. python3 -m pytest tests/test_custom_layer_template.py
```

## What exists

```
app/custom/
├── _template/               <- copy this to start a new project
│   ├── README.md            the actual step-by-step guide
│   ├── config.yaml           heavily commented placeholder
│   ├── raw_loader.py         extraction stub (raises NotImplementedError)
│   ├── custom_filters.py     empty registration dict + commented example
│   └── bootstrap.py          generic wiring (config + raw data -> SearchEngine)
│
├── legal/                   <- a project built BY FOLLOWING the template
│   ├── config.yaml           real (pre-existing) legal field declarations
│   ├── raw_loader.py         a small embedded sample dataset
│   ├── custom_filters.py     empty (this project needs no overrides)
│   └── bootstrap.py          copied from the template, unmodified
│
└── books/                   <- the second project, source doc's own §4/§11 example
    ├── config.yaml            title/author/publication_year/subjects (§9)
    ├── raw_loader.py          sample catalog, including Ibn Sa'd's "Kitab
    │                          al-Tabaqat al-Kabir" -- the exact book §4 uses
    ├── custom_filters.py      ONE override: title -> fuzzy matching
    ├── fuzzy_title_filter.py  the real reference custom filter (Phase 3, item 2)
    └── bootstrap.py           copied from the template, unmodified
```

`app/custom/legal/` and `app/custom/books/` together are the proof the
template is real, not just documentation:
`tests/test_custom_layer_template.py` and
`tests/test_fuzzy_title_filter.py` build a `SearchEngine` from each and
run real searches against them — using nothing but the four/five-file
pattern above, with zero project-specific code anywhere in `app/core/`
or `app/api/`. Between the two, they demonstrate both ends of the
override spectrum: legal needs zero custom filters (the generic default
is correct as-is), books needs exactly one (fuzzy title matching) —
matching the source doc's own architecture diagram (§11): `Legal Search
→ Custom filters` (unspecified/none needed yet) vs. `Book Search → Fuzzy
title`.

## The registration pattern, in one sentence

A project's custom filters are a plain `dict[field_name, FilterSubclass]`
(`CustomFilterMap`, from `app.core.filtering`) built once in
`custom_filters.py` and passed straight into
`SearchEngine.from_config_path(..., custom_filters=...)` — no decorators,
no global registry, no core code touched. See `docs/override-mechanism.md`
(or `app/core/filtering/config_loader.py`'s module docstring, "Phase 2
addition") for the underlying `generic default -> use-case configuration
-> optional custom override` chain this pattern rests on, and
`app/custom/_template/README.md` for the concrete steps.

## What's deliberately not built here

- **The custom-vs-generic promotion rule doc.** Phase 3, item 3 — this
  document doesn't attempt to codify when something belongs in
  `custom_filters.py` vs. being promoted into `app/core/filtering/`.
  `app/custom/legal/fuzzy_title_filter.py`'s module docstring previews
  the rule of thumb (a second project independently needing the same
  thing is the promotion signal) but the dedicated doc isn't written yet.
- **A full documentation pass** (architecture diagram, config schema
  reference, filter type reference). That's Phase 6.

For the real custom filter example (Phase 3, item 2 — fuzzy title
matching), see `docs/fuzzy-title-filter.md`.