"""
tests/test_pilot_definition_of_done.py

Roadmap's stated Definition of Done:

    "pilot app runs fully from config + custom layer with zero
    use-case-specific code in core/."

app/custom/legal_pilot/ is that pilot: the five filters called for by
the source doc's §4 running example (publication date, promulgation
date, document type, issuing authority, legal status), plus a bonus
`title` contains-filter, over a 12-record realistic corpus -- built
entirely from config.yaml + raw_loader.py + an intentionally EMPTY
custom_filters.py (app/custom/legal_pilot/custom_filters.py).

This is a separate project from app/custom/legal/, which is the
worked example of the TEMPLATE mechanism itself (kept small and
load-bearing for tests/test_custom_layer_template.py) and does not
cover issuing_authority or legal_status. legal_pilot/ is the actual
genericity check the roadmap describes: a full field set, run
against the real, unmodified app/core/ + app/api/ stack.

No file under app/core/ or app/api/ was added, removed, or modified to
build this pilot -- see docs/pilot-notes.md for the explicit
record of what was considered as a potential core change and why each
candidate was rejected (deferred v1 scope, or a UI-only concern that
doesn't require a schema change) rather than added ad hoc.
"""
from __future__ import annotations

import pytest

from app.api import SearchEngine, SearchRequest
from app.api.errors import BadQueryError
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord
from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery


def _fake_embedding(seed: int, dim: int = 4) -> Embedding:
    """Deterministic pseudo-embedding -- this pilot has no real
    embedding model wired up; only the semantic-search PATH is under
    test here, not retrieval quality."""
    import random

    rng = random.Random(seed)
    return Embedding(vector=[rng.uniform(-1, 1) for _ in range(dim)], model_id="fake-pilot-embedder-v0")


@pytest.fixture()
def pilot_engine():
    from app.custom.legal_pilot.bootstrap import build_search_engine
    from app.custom.legal_pilot.raw_loader import load_raw_records
    from app.core.config import load_use_case_config
    from app.core.ingestion import ingest_raw_records

    config = load_use_case_config("app/custom/legal_pilot/config.yaml")
    report = ingest_raw_records(load_raw_records(), config.to_metadata_schema())
    assert report.is_clean, report.summary

    embeddings = {doc.id: _fake_embedding(hash(doc.id)) for doc in report.valid_documents}
    embedding_provider = InlineEmbeddingProvider(
        [
            EmbeddedDocumentRecord(id=doc.id, text=doc.text, metadata={}, embedding=embeddings[doc.id])
            for doc in report.valid_documents
        ]
    )
    return SearchEngine.from_config_path(
        "app/custom/legal_pilot/config.yaml",
        report.valid_documents,
        custom_filters={},
        embedding_provider=embedding_provider,
    )


def test_pilot_ingests_all_twelve_records_cleanly():
    from app.custom.legal_pilot.raw_loader import load_raw_records
    from app.core.config import load_use_case_config
    from app.core.ingestion import ingest_raw_records

    config = load_use_case_config("app/custom/legal_pilot/config.yaml")
    report = ingest_raw_records(load_raw_records(), config.to_metadata_schema())
    assert report.is_clean
    assert len(report.valid_documents) == 12


def test_pilot_declares_exactly_the_five_required_filters_plus_title(pilot_engine):
    assert set(pilot_engine._filters.keys()) == {
        "document_type",
        "publication_date",
        "promulgation_date",
        "issuing_authority",
        "legal_status",
        "title",
    }


def test_pilot_custom_filters_map_is_empty():
    """The DoD-relevant fact: none of the five required filters, nor
    the bonus title filter, needed a custom override for this pilot."""
    from app.custom.legal_pilot.custom_filters import CUSTOM_FILTERS

    assert CUSTOM_FILTERS == {}


def test_pilot_document_type_equality_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"document_type": "dahir"},
    ))
    assert {hit.id for hit in page.hits} == {"legal_text_0001", "legal_text_0005", "legal_text_0010"}


def test_pilot_issuing_authority_equality_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"issuing_authority": "chef_du_gouvernement"},
    ))
    assert page.total_hits == 5


def test_pilot_legal_status_equality_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"legal_status": "abroge"},
    ))
    assert {hit.id for hit in page.hits} == {"legal_text_0009", "legal_text_0011"}


def test_pilot_publication_date_range_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"publication_date": {"min": "2020-01-01", "max": "2023-12-31"}},
    ))
    assert page.total_hits == 3


def test_pilot_promulgation_date_range_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"promulgation_date": {"min": "1990-01-01", "max": "2010-12-31"}},
    ))
    assert page.total_hits == 4


def test_pilot_combined_filters_and_lexical_search(pilot_engine):
    """AND semantics across two declared filters, plus a lexical rule,
    all narrowing down to one specific document -- the actual
    integration seam (§3's 'filters narrow the candidate set, search
    ranks within it')."""
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=["marches"]),
        filters={"document_type": "decret", "legal_status": "modifie"},
    ))
    assert page.total_hits == 1
    assert page.hits[0].id == "legal_text_0002"


def test_pilot_bonus_title_contains_filter(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=[]),
        filters={"title": "marches publics"},
    ))
    assert page.total_hits == 2


def test_pilot_semantic_search_path_runs_and_hydrates_metadata(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        semantic=[SemanticQuery(vector=[0.1, 0.2, 0.3, 0.4])],
    ))
    assert page.total_hits > 0
    assert all(hit.metadata for hit in page.hits)


def test_pilot_unknown_filter_field_is_a_bad_query_not_a_silent_noop(pilot_engine):
    with pytest.raises(BadQueryError):
        pilot_engine.search(SearchRequest(
            lexical=LexicalQuery(mandatories=[]),
            filters={"not_a_real_field": "x"},
        ))


def test_pilot_no_match_query_is_a_normal_empty_page_not_an_error(pilot_engine):
    page = pilot_engine.search(SearchRequest(
        lexical=LexicalQuery(mandatories=["nonexistent_term_xyz"]),
    ))
    assert page.total_hits == 0
    assert page.hits == []
