#!/usr/bin/env python3
r"""
scripts/demo_API.py

Run this from the repo root to SEE API (the common API layer +
override mechanism) working on the terminal: the same fake "gadgets"
corpus/config/embeddings used by
tests/test_API_definition_of_done.py, run through several
SearchRequests -- filter-only, semantic+lexical combined, pagination,
the §6 custom override actually changing behavior, and each of the
error paths -- with every stage's structured log line AND the final
result printed.

    PYTHONPATH=. python3 scripts/demo_API.py

This is a demo/inspection script, not a test -- see
tests/test_API_definition_of_done.py and tests/test_api_orchestrator.py
for the assertions that pin these exact numbers down as regression tests.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app.api import BadConfigError, BadQueryError, SearchEngine, SearchRequest
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.filtering import Filter, load_filters
from app.core.ingestion import ingest_raw_records
from app.core.schema.embedding import EmbeddedDocumentRecord, Embedding
from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery

# ---------------------------------------------------------------------------
# Fixed fake config: 'category' is overridden (§6) with case-insensitive
# equality; everything else uses the generic filters as-is.
# ---------------------------------------------------------------------------

CONFIG_YAML = """
schema_version: 1
filters:
  category:
    type: string
    required: true
    operation: equality
  in_stock:
    type: bool
    operation: equality
  rating:
    type: float
    operation: range
  tags:
    type: list
    item_type: string
    operation: contains
search:
  semantic:
    enabled: true
    multi_query_combination: max_score
  lexical:
    enabled: true
  ranking:
    strategy: weighted_sum
    weights:
      semantic: 0.6
      lexical: 0.4
  pagination:
    default_page_size: 10
    max_page_size: 50
frontend:
  branding:
    title: "Gadgets"
"""


class CaseInsensitiveCategoryFilter(Filter):
    """The §6 custom override demonstrated below: same declared
    operation ('equality') as the generic filter, different behavior."""

    operation = "equality"

    def apply(self, records, field, params):
        if not params:
            return list(records)
        values = params if isinstance(params, (list, tuple, set)) else [params]
        targets = {str(v).casefold() for v in values}
        return [
            r
            for r in records
            if r.metadata.get(field) is not None and str(r.metadata[field]).casefold() in targets
        ]


RAW_RECORDS = [
    {
        "id": "gadget-1",
        "text": "A sturdy wireless mouse for office use.",
        "metadata": {"category": "Peripherals", "in_stock": True, "rating": 4.5, "tags": ["wireless", "office"]},
    },
    {
        "id": "gadget-2",
        "text": "A mechanical keyboard with RGB lighting.",
        "metadata": {"category": "peripherals", "in_stock": False, "rating": 4.8, "tags": ["mechanical", "office"]},
    },
    {
        "id": "gadget-3",
        "text": "A 4K gaming monitor with high refresh rate.",
        "metadata": {"category": "displays", "in_stock": True, "rating": 4.2, "tags": ["gaming"]},
    },
    {
        "id": "gadget-4",
        "text": "A budget webcam with mediocre low-light performance.",
        "metadata": {"category": "peripherals", "in_stock": True, "rating": 3.1, "tags": ["office"]},
    },
]

# Hand-picked 2D embeddings: gadget-1/2/4 cluster near (1, 0)
# ("peripherals"-ish), gadget-3 sits near (0, 1) ("display"-ish).
FAKE_EMBEDDINGS = {
    "gadget-1": [1.0, 0.1],
    "gadget-2": [0.9, 0.0],
    "gadget-3": [0.0, 1.0],
    "gadget-4": [0.8, 0.2],
}


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def print_page(page) -> None:
    print(
        f"  page={page.page}  page_size={page.page_size}  "
        f"total_hits={page.total_hits}  total_pages={page.total_pages}  "
        f"has_previous={page.has_previous}  has_next={page.has_next}"
    )
    if not page.hits:
        print("  hits: (none)")
        return
    print(f"  {'id':10s}{'score':>10s}  matched_fields  metadata")
    for hit in page.hits:
        score = f"{hit.score:.4f}" if hit.score is not None else "  n/a"
        print(f"  {hit.id:10s}{score:>10s}  {hit.matched_fields}  {hit.metadata}")


def build_engine() -> SearchEngine:
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(CONFIG_YAML)

        config, filters = load_filters(
            config_path, custom_filters={"category": CaseInsensitiveCategoryFilter}
        )

        schema = config.to_metadata_schema()
        report = ingest_raw_records(RAW_RECORDS, schema)
        assert report.is_clean, report.summary

        embedded_records = [
            EmbeddedDocumentRecord(
                id=r["id"],
                text=r["text"],
                metadata={},
                embedding=Embedding(vector=FAKE_EMBEDDINGS[r["id"]], model_id="fake-2d-v1"),
            )
            for r in RAW_RECORDS
        ]
        embedding_provider = InlineEmbeddingProvider(embedded_records)

        return SearchEngine(
            config, filters, report.valid_documents, embedding_provider=embedding_provider
        )


def main() -> None:
    # Structured logs (app/api/observability.py) go through the standard
    # `logging` module -- turn them on so the demo shows the same
    # filtering -> search -> ranking -> pagination log lines a real
    # deployment would emit.
    logging.basicConfig(level=logging.INFO, format="  [log] %(name)s %(message)s")

    section("FIXED FAKE CORPUS")
    for record in RAW_RECORDS:
        print(f"  {record['id']:10s} {record['metadata']}  text=\"{record['text']}\"")

    section("FIXED FAKE EMBEDDINGS (2D)")
    for doc_id, vector in FAKE_EMBEDDINGS.items():
        print(f"  {doc_id:10s} -> {vector}")

    engine = build_engine()

    # -----------------------------------------------------------------
    # 1) Custom override in action: 'Peripherals' matches both
    #    'Peripherals' AND 'peripherals' -- the generic EqualityFilter
    #    would only match the exact case.
    # -----------------------------------------------------------------
    section("1) §6 OVERRIDE: category equality is case-INSENSITIVE for this project")
    request = SearchRequest(lexical=LexicalQuery(), filters={"category": "PERIPHERALS"})
    print(f"request = {request.model_dump()}\n")
    page = engine.search(request)
    print_page(page)
    print("  (gadget-1 'Peripherals' and gadget-2/gadget-4 'peripherals' ALL match)")

    # -----------------------------------------------------------------
    # 2) Full pipeline: filter -> semantic + lexical -> rank -> paginate
    # -----------------------------------------------------------------
    section("2) FULL PIPELINE: filter + semantic + lexical -> rank -> paginate")
    request = SearchRequest(
        semantic=[SemanticQuery(vector=[1.0, 0.0])],
        lexical=LexicalQuery(first_of=["wireless", "webcam"]),
        filters={"category": "Peripherals", "in_stock": True},
        page=1,
        page_size=10,
    )
    print(f"request = {request.model_dump()}\n")
    page = engine.search(request)
    print_page(page)
    print("  (gadget-2 excluded by in_stock=True; gadget-3 excluded by category;")
    print("   gadget-1 ranks first: strong semantic match AND lexical 'wireless' hit)")

    # -----------------------------------------------------------------
    # 3) Pagination across pages
    # -----------------------------------------------------------------
    section("3) PAGINATION: match-all lexical rule, page_size=2")
    base_request = SearchRequest(lexical=LexicalQuery(), page_size=2)
    page_1 = engine.search(base_request)
    print("page 1:")
    print_page(page_1)
    page_2 = engine.search(base_request.model_copy(update={"page": 2}))
    print("page 2:")
    print_page(page_2)

    # -----------------------------------------------------------------
    # 4) No results -- NOT an error, just an empty page + a log event
    # -----------------------------------------------------------------
    section("4) NO RESULTS: well-formed but overly strict filters (not an error)")
    request = SearchRequest(
        lexical=LexicalQuery(), filters={"category": "peripherals", "rating": {"min": 100.0}}
    )
    print(f"request = {request.model_dump()}\n")
    page = engine.search(request)
    print_page(page)
    print("  (see the 'search.no_results' log line above -- no exception was raised)")

    # -----------------------------------------------------------------
    # 5) Error taxonomy: BadQueryError vs BadConfigError
    # -----------------------------------------------------------------
    section("5) ERROR TAXONOMY")
    print(
        "  NOTE: each case below logs a full traceback via logger.exception()\n"
        "  as part of the '{stage}.failed' structured log event (this is\n"
        "  correct, intentional behavior for a real error -- see\n"
        "  app/api/observability.py). The script does NOT crash: every\n"
        "  exception is caught immediately below and printed as\n"
        "  'BadQueryError: ...' / 'BadConfigError: ...'.\n"
    )


    print("-- unknown filter field:")
    try:
        engine.search(SearchRequest(lexical=LexicalQuery(), filters={"not_a_real_field": "x"}))
    except BadQueryError as exc:
        print(f"  BadQueryError: {exc}")

    print("\n-- filter value of the wrong type:")
    try:
        engine.search(SearchRequest(lexical=LexicalQuery(), filters={"in_stock": "yes"}))
    except BadQueryError as exc:
        print(f"  BadQueryError: {exc}")

    print("\n-- semantic request with no embedding_provider configured:")
    engine_no_embeddings = SearchEngine(engine._config, engine._filters, engine._documents)
    try:
        engine_no_embeddings.search(SearchRequest(semantic=[SemanticQuery(vector=[1.0, 0.0])]))
    except BadConfigError as exc:
        print(f"  BadConfigError: {exc}")

    print("\n-- malformed config.yaml (operation incompatible with field type):")
    with tempfile.TemporaryDirectory() as tmp:
        bad_config_path = Path(tmp) / "config.yaml"
        bad_config_path.write_text(
            """
schema_version: 1
filters:
  in_stock:
    type: bool
    operation: contains
search: {}
frontend:
  branding:
    title: "Gadgets"
"""
        )
        try:
            SearchEngine.from_config_path(bad_config_path, documents=[])
        except BadConfigError as exc:
            print(f"  BadConfigError: {exc}")

    print()


if __name__ == "__main__":
    main()
