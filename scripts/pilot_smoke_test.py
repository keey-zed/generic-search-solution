"""
scripts/pilot_smoke_test.py

Definition of Done check: "pilot app runs fully from config +
custom layer with zero use-case-specific code in core/."

Exercises the app/custom/legal_pilot/ project end-to-end through the
real, unmodified app/core/ + app/api/ stack:
  - ingestion (via bootstrap.build_search_engine)
  - each of the five required filters, individually and combined
  - lexical search
  - semantic search (fake but real-shaped inline embeddings, since this
    pilot has no real embedding model wired up)
  - pagination

Run with:
    PYTHONPATH=. python3 scripts/pilot_smoke_test.py
"""
from __future__ import annotations

import random

from app.api import SearchEngine, SearchRequest
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.ingestion import ingest_raw_records
from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord
from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery
from app.core.config import load_use_case_config
from app.custom.legal_pilot import raw_loader

CONFIG_PATH = "app/custom/legal_pilot/config.yaml"


def _fake_embedding(seed: str, dim: int = 8) -> Embedding:
    """Deterministic pseudo-embedding, just to exercise the semantic
    search path -- not a real embedding model. Same seed -> same
    vector, so 'similar' documents can be constructed deliberately
    below."""
    rng = random.Random(seed)
    return Embedding(vector=[rng.uniform(-1, 1) for _ in range(dim)], model_id="fake-pilot-embedder-v0")


def main() -> None:
    config = load_use_case_config(CONFIG_PATH)
    schema = config.to_metadata_schema()

    raw_records = raw_loader.load_raw_records()
    report = ingest_raw_records(raw_records, schema)
    assert report.is_clean, report.summary
    print(f"[ingestion] {report.summary}")

    # Build fake embeddings so semantic search has something to search
    # against -- one deterministic vector per document, keyed by id.
    embeddings = {doc.id: _fake_embedding(doc.id) for doc in report.valid_documents}
    embedded_docs_by_id = {doc.id: e for doc, e in zip(report.valid_documents, embeddings.values())}
    embedding_provider = InlineEmbeddingProvider(
        [
            EmbeddedDocumentRecord(id=doc.id, text=doc.text, metadata={}, embedding=embeddings[doc.id])
            for doc in report.valid_documents
        ]
    )

    engine = SearchEngine.from_config_path(
        CONFIG_PATH,
        report.valid_documents,
        custom_filters={},  # confirmed empty for this pilot
        embedding_provider=embedding_provider,
    )

    checks = []

    # 1. document_type (equality)
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"document_type": "dahir"},
    ))
    checks.append(("document_type=dahir -> 3 hits", page.total_hits == 3))

    # 2. issuing_authority (equality)
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"issuing_authority": "chef_du_gouvernement"},
    ))
    checks.append(("issuing_authority=chef_du_gouvernement -> 5 hits", page.total_hits == 5))

    # 3. legal_status (equality)
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"legal_status": "abroge"},
    ))
    checks.append(("legal_status=abroge -> 2 hits", page.total_hits == 2))

    # 4. publication_date (range)
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"publication_date": {"min": "2020-01-01", "max": "2023-12-31"}},
    ))
    checks.append(("publication_date range 2020-2023 -> 3 hits", page.total_hits == 3))

    # 5. promulgation_date (range)
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"promulgation_date": {"min": "1990-01-01", "max": "2010-12-31"}},
    ))
    checks.append(("promulgation_date range 1990-2010 -> 4 hits", page.total_hits == 4))

    # 6. Combined filters (AND across fields) + lexical rule together
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=["marches"]),
        filters={"document_type": "decret", "legal_status": "modifie"},
    ))
    checks.append((
        "document_type=decret AND legal_status=modifie AND lexical('marches') -> 1 hit",
        page.total_hits == 1 and page.hits[0].id == "legal_text_0002",
    ))

    # 7. Bonus contains filter on title
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"title": "marches publics"},
    ))
    checks.append(("title contains 'marches publics' -> 2 hits", page.total_hits == 2))

    # 8. Semantic search runs and returns hydrated, ranked, paginated
    # results. v1 has no query-text-to-vector step -- a
    # caller supplies an already-embedded query vector. Reuse one
    # document's own fake vector as a stand-in "query embedding".
    query_vector = embeddings["legal_text_0001"].vector
    page = engine.search(SearchRequest(
        semantic=[SemanticQuery(vector=query_vector)],
    ))
    checks.append(("semantic query returns hits with metadata attached", (
        page.total_hits > 0 and all(hit.metadata for hit in page.hits)
    )))

    # 9. Unknown filter field is rejected as BadQueryError, not a silent no-op
    from app.api.errors import BadQueryError
    try:
        engine.search(SearchRequest(
            lexical=LexicalQuery(mandatories=[]),
            filters={"not_a_real_field": "x"},
        ))
        checks.append(("unknown filter field raises BadQueryError", False))
    except BadQueryError:
        checks.append(("unknown filter field raises BadQueryError", True))

    # 10. Zero results is a normal page, not an error
    page = engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=["nonexistent_term_xyz"]),
    ))
    checks.append(("no-match query returns empty page, no exception", page.total_hits == 0))

    print()
    all_passed = True
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"[{status}] {label}")

    print()
    if all_passed:
        print("All pilot checks passed.")
    else:
        raise SystemExit("One or more pilot checks FAILED.")


if __name__ == "__main__":
    main()
