"""
app/custom/_template/raw_loader.py

STEP 2 of adopting this template for a new project: replace the body of
`load_raw_records()` with whatever it takes to turn YOUR raw data (an
XML dump, a CSV export, rows from a database, scraped HTML, ...) into
the ONE shape the rest of this project understands -- a list of plain
dicts shaped like:

    {"id": "<unique string>", "text": "<searchable text>", "metadata": {...}}

`metadata` keys should match the field names you declared under
`filters:` in config.yaml (plus any other metadata you want stored but
not necessarily filterable). Values can be raw (e.g. a date as a string
like "2024-01-01") -- `app.core.ingestion.ingest_raw_records()`
(called by bootstrap.py, not here) type-checks and coerces them against
your config.yaml schema; you don't need to do that yourself.

This is intentionally the ONLY file in your project that needs to know
your raw data's original format (see Track B's ingestion deliverable,
docs/ingestion.md: "actual project-specific extraction ... belongs in
each project's custom layer, not core"). Everything downstream --
validation, type coercion, filtering, search, ranking -- is generic and
works unchanged no matter what this function returns, as long as it
returns records shaped like the above.

Do NOT, in this file:
  - validate or coerce metadata types (that's ingestion's job, not this
    file's -- a date string does not need to become a `date` object here)
  - filter, search, or rank anything
  - import anything from app.core.filtering or app.core.search

This file's only job is "get my data into the standard shape."
"""
from __future__ import annotations

from typing import Any


def load_raw_records() -> list[dict[str, Any]]:
    """Replace this with real extraction logic for your project.

    Example of the shape to return:

        [
            {
                "id": "doc-1",
                "text": "The full searchable text of this document.",
                "metadata": {
                    "category": "example",
                    "release_date": "2024-01-01",
                    "tags": ["example", "placeholder"],
                },
            },
            ...
        ]
    """
    raise NotImplementedError(
        "Replace load_raw_records() with your project's own extraction "
        "logic -- see this file's module docstring. See "
        "app/custom/legal/raw_loader.py for a filled-in example."
    )