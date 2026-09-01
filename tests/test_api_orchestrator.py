"""
tests/test_api_orchestrator.py

Focused unit tests for `app/api/orchestrator.py` and `app/api/request.py`
-- one thing at a time, complementing the full round-trip covered by
tests/test_API_definition_of_done.py and the override seam covered by
tests/test_override_mechanism.py.
"""
from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.api.errors import BadConfigError, BadQueryError
from app.api.orchestrator import SearchEngine, _hydrate_metadata
from app.api.request import SearchRequest
from app.core.config.models import (
    BrandingConfig,
    FilterFieldConfig,
    FrontendConfig,
    SearchConfig,
    UseCaseConfig,
)
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.schema.embedding import EmbeddedDocumentRecord, Embedding
from app.core.schema.metadata_types import MetadataFieldType, NormalizedDocument
from app.core.schema.search_hit import SearchHit
from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery


def _config(**filters: FilterFieldConfig) -> UseCaseConfig:
    return UseCaseConfig(
        schema_version=1,
        filters=filters,
        search=SearchConfig(),
        frontend=FrontendConfig(branding=BrandingConfig(title="Test")),
    )


def doc(id_, text="text", **metadata) -> NormalizedDocument:
    return NormalizedDocument(id=id_, text=text, metadata=metadata)


# ---------------------------------------------------------------------------
# SearchRequest -- "at least one query mode" validation
# ---------------------------------------------------------------------------


def test_request_requires_semantic_or_lexical():
    with pytest.raises(ValidationError, match="at least one"):
        SearchRequest(filters={"x": 1})


def test_request_accepts_semantic_only():
    SearchRequest(semantic=[SemanticQuery(vector=[1.0])])


def test_request_accepts_lexical_only():
    SearchRequest(lexical=LexicalQuery())


# ---------------------------------------------------------------------------
# _hydrate_metadata
# ---------------------------------------------------------------------------


def test_hydrate_metadata_fills_in_full_metadata():
    hits = [SearchHit(id="a", score=1.0, metadata={})]
    by_id = {"a": doc("a", category="books")}

    hydrated = _hydrate_metadata(hits, by_id)

    assert hydrated[0].metadata == {"category": "books"}


def test_hydrate_metadata_drops_hit_with_unknown_id():
    hits = [SearchHit(id="ghost", score=1.0)]
    hydrated = _hydrate_metadata(hits, {})
    assert hydrated == []


# ---------------------------------------------------------------------------
# Filtering stage
# ---------------------------------------------------------------------------


def test_unknown_filter_field_raises_bad_query_error():
    config = _config(category=FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"))
    engine = SearchEngine(config, {}, [doc("a", category="x")])
    # filters dict passed to SearchEngine must match config.filters keys;
    # build via build_filters_from_config in real use -- here we bypass
    # that to isolate _apply_filters' own validation.
    from app.core.filtering import build_filters_from_config

    engine = SearchEngine(config, build_filters_from_config(config), [doc("a", category="x")])

    request = SearchRequest(lexical=LexicalQuery(), filters={"nope": "x"})
    with pytest.raises(BadQueryError, match="unknown filter field"):
        engine.search(request)


def test_filter_value_type_mismatch_raises_bad_query_error():
    from app.core.filtering import build_filters_from_config

    config = _config(in_stock=FilterFieldConfig(type=MetadataFieldType.BOOL, operation="equality"))
    engine = SearchEngine(config, build_filters_from_config(config), [doc("a", in_stock=True)])

    request = SearchRequest(lexical=LexicalQuery(), filters={"in_stock": "yes"})
    with pytest.raises(BadQueryError, match="filters\\['in_stock'\\]"):
        engine.search(request)


def test_no_filters_is_a_noop_on_the_full_corpus():
    from app.core.filtering import build_filters_from_config

    config = _config(category=FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"))
    documents = [doc("a", category="x"), doc("b", category="y")]
    engine = SearchEngine(config, build_filters_from_config(config), documents)

    page = engine.search(SearchRequest(lexical=LexicalQuery(), filters={}))
    assert {h.id for h in page.hits} == {"a", "b"}


# ---------------------------------------------------------------------------
# Semantic stage
# ---------------------------------------------------------------------------


def test_semantic_disabled_in_config_raises_bad_query_error():
    from app.core.config.models import SemanticSearchConfig

    config = UseCaseConfig(
        schema_version=1,
        filters={},
        search=SearchConfig(semantic=SemanticSearchConfig(enabled=False)),
        frontend=FrontendConfig(branding=BrandingConfig(title="Test")),
    )
    engine = SearchEngine(config, {}, [doc("a")])

    with pytest.raises(BadQueryError, match="search.semantic.enabled"):
        engine.search(SearchRequest(semantic=[SemanticQuery(vector=[1.0])]))


def test_semantic_without_embedding_provider_raises_bad_config_error():
    config = _config()
    engine = SearchEngine(config, {}, [doc("a")])  # no embedding_provider

    with pytest.raises(BadConfigError, match="embedding_provider"):
        engine.search(SearchRequest(semantic=[SemanticQuery(vector=[1.0])]))


def test_semantic_candidates_missing_all_embeddings_yields_no_results_not_an_error():
    config = _config()
    provider = InlineEmbeddingProvider([])  # empty: no ids known
    engine = SearchEngine(config, {}, [doc("a")], embedding_provider=provider)

    page = engine.search(SearchRequest(semantic=[SemanticQuery(vector=[1.0])]))
    assert page.hits == []
    assert page.total_hits == 0


def test_semantic_search_scoped_to_filtered_candidates_only():
    """A document excluded by filtering must never appear in semantic
    results, even if it would otherwise score highest -- proves search
    runs WITHIN the filtered candidate set, not the whole corpus."""
    from app.core.filtering import build_filters_from_config

    config = _config(category=FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"))
    documents = [doc("keep", category="books"), doc("exclude", category="movies")]

    records = [
        EmbeddedDocumentRecord(
            id="keep", text="t", metadata={}, embedding=Embedding(vector=[1.0, 0.0], model_id="m")
        ),
        EmbeddedDocumentRecord(
            id="exclude", text="t", metadata={}, embedding=Embedding(vector=[1.0, 0.0], model_id="m")
        ),
    ]
    provider = InlineEmbeddingProvider(records)

    engine = SearchEngine(
        config, build_filters_from_config(config), documents, embedding_provider=provider
    )

    request = SearchRequest(
        semantic=[SemanticQuery(vector=[1.0, 0.0])], filters={"category": "books"}
    )
    page = engine.search(request)

    assert {h.id for h in page.hits} == {"keep"}


# ---------------------------------------------------------------------------
# Lexical stage
# ---------------------------------------------------------------------------


def test_lexical_disabled_in_config_raises_bad_query_error():
    from app.core.config.models import LexicalSearchConfig

    config = UseCaseConfig(
        schema_version=1,
        filters={},
        search=SearchConfig(lexical=LexicalSearchConfig(enabled=False)),
        frontend=FrontendConfig(branding=BrandingConfig(title="Test")),
    )
    engine = SearchEngine(config, {}, [doc("a", text="hello")])

    with pytest.raises(BadQueryError, match="search.lexical.enabled"):
        engine.search(SearchRequest(lexical=LexicalQuery(first_of=["hello"])))


def test_lexical_none_means_lexical_stage_does_not_run():
    """lexical=None must skip the lexical stage entirely -- distinct from
    LexicalQuery() (both fields empty), which IS a match-all rule that
    DOES run. Proven here via a semantic-only request that still returns
    correctly (if lexical ran with a bad implicit default, this would
    misbehave)."""
    config = _config()
    records = [
        EmbeddedDocumentRecord(
            id="a", text="t", metadata={}, embedding=Embedding(vector=[1.0], model_id="m")
        )
    ]
    provider = InlineEmbeddingProvider(records)
    engine = SearchEngine(config, {}, [doc("a")], embedding_provider=provider)

    page = engine.search(SearchRequest(semantic=[SemanticQuery(vector=[1.0])]))
    assert {h.id for h in page.hits} == {"a"}


# ---------------------------------------------------------------------------
# Structured logging (deliverable 3) -- smoke test that stages actually log
# ---------------------------------------------------------------------------


def test_stages_emit_structured_log_records(caplog):
    from app.core.filtering import build_filters_from_config

    config = _config(category=FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"))
    documents = [doc("a", category="x")]
    engine = SearchEngine(config, build_filters_from_config(config), documents)

    with caplog.at_level(logging.INFO, logger="app.api"):
        engine.search(SearchRequest(lexical=LexicalQuery(), filters={"category": "x"}))

    messages = [record.message for record in caplog.records]
    assert any(m == "filtering.started" for m in messages)
    assert any(m == "filtering.finished" for m in messages)
    assert any(m == "search.started" for m in messages)
    assert any(m == "ranking.finished" for m in messages)
    assert any(m == "pagination.finished" for m in messages)


def test_no_results_logs_distinct_event_not_raised_as_error(caplog):
    from app.core.filtering import build_filters_from_config

    config = _config(category=FilterFieldConfig(type=MetadataFieldType.STRING, operation="equality"))
    documents = [doc("a", category="x")]
    engine = SearchEngine(config, build_filters_from_config(config), documents)

    with caplog.at_level(logging.INFO, logger="app.api"):
        page = engine.search(SearchRequest(lexical=LexicalQuery(), filters={"category": "nonexistent"}))

    assert page.total_hits == 0
    assert any(record.message == "search.no_results" for record in caplog.records)
