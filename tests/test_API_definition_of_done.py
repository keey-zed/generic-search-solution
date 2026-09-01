"""
tests/test_API_definition_of_done.py

API's stated Definition of Done:

    "a full request/response round-trip works against fake data, fake
    embeddings, and a fake config -- with one filter overridden in a
    'custom' stub -- end-to-end, with automated tests."

Mirrors the shape of tests/test_track_b_definition_of_done.py and
tests/test_Retrieval_definition_of_done.py: one file that runs the WHOLE 
pipeline together, exactly as the DoD describes it, rather than
re-testing individual pieces already covered elsewhere (orchestrator
stage unit tests live in test_api_orchestrator.py; the override seam
itself is proven in isolation in test_override_mechanism.py).

The fake domain here is "gadgets" again, specifically to keep demonstrating genericity: nothing in
`app/api/` knows or cares what "category"/"tags"/"rating" mean.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.api import BadConfigError, BadQueryError, SearchEngine, SearchRequest
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.filtering import Filter
from app.core.ingestion import ingest_raw_records
from app.core.schema.embedding import EmbeddedDocumentRecord, Embedding
from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery

# ---------------------------------------------------------------------------
# Fake config: one field overridden via a custom stub (case-insensitive
# equality on 'category'), the rest generic -- same override shape proven
# in isolation by test_override_mechanism.py, exercised here as part of a
# full request/response round trip.
# ---------------------------------------------------------------------------

_GADGETS_CONFIG_YAML = """
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


class _CaseInsensitiveCategoryFilter(Filter):
    """The 'custom stub' the DoD calls for: overrides the generic
    equality filter for exactly one field ('category'), per §6."""

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


# ---------------------------------------------------------------------------
# Fake data: raw records (pre-ingestion) covering every filter field, plus
# text content that a lexical rule and a semantic query can both find.
# ---------------------------------------------------------------------------

_RAW_RECORDS = [
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

# Fake 2D embeddings, hand-picked so cosine similarity is easy to reason
# about: gadget-1/2/4 cluster near (1, 0) ("peripherals"-ish), gadget-3
# sits near (0, 1) ("display"-ish).
_FAKE_EMBEDDINGS = {
    "gadget-1": [1.0, 0.1],
    "gadget-2": [0.9, 0.0],
    "gadget-3": [0.0, 1.0],
    "gadget-4": [0.8, 0.2],
}


@pytest.fixture()
def gadgets_engine(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_GADGETS_CONFIG_YAML)

    embedded_records = [
        EmbeddedDocumentRecord(
            id=r["id"],
            text=r["text"],
            metadata={},  # metadata typing/coercion happens via ingestion below, not here
            embedding=Embedding(vector=_FAKE_EMBEDDINGS[r["id"]], model_id="fake-2d-v1"),
        )
        for r in _RAW_RECORDS
    ]
    embedding_provider = InlineEmbeddingProvider(embedded_records)

    from app.core.filtering import load_filters

    config, filters = load_filters(config_path, custom_filters={"category": _CaseInsensitiveCategoryFilter})
    schema = config.to_metadata_schema()
    report = ingest_raw_records(_RAW_RECORDS, schema)
    assert report.is_clean, report.summary

    return SearchEngine(
        config,
        filters,
        report.valid_documents,
        embedding_provider=embedding_provider,
    )


# ---------------------------------------------------------------------------
# The full round trip
# ---------------------------------------------------------------------------


def test_full_round_trip_filter_then_semantic_and_lexical(gadgets_engine):
    """Filters narrow to in-stock peripherals (via the CASE-INSENSITIVE
    custom override -- 'Peripherals' and 'peripherals' both match), then
    a semantic query (near the 'peripherals' embedding cluster) plus a
    lexical rule both run scoped to that narrowed set, and the merged,
    ranked, paginated result comes back as one SearchResultPage.
    """
    request = SearchRequest(
        semantic=[SemanticQuery(vector=[1.0, 0.0])],
        lexical=LexicalQuery(first_of=["wireless", "webcam"]),
        filters={"category": "Peripherals", "in_stock": True},
        page=1,
        page_size=10,
    )

    page = gadgets_engine.search(request)

    # gadget-2 excluded by in_stock=True; gadget-3 excluded by category.
    # gadget-1 (wireless) and gadget-4 (webcam) both match the lexical
    # rule; gadget-1 also has a strong semantic score.
    result_ids = [hit.id for hit in page.hits]
    assert set(result_ids) == {"gadget-1", "gadget-4"}
    assert page.total_hits == 2
    assert page.page == 1
    assert page.has_next is False
    assert page.has_previous is False

    # Metadata was hydrated onto the final hits (retrieval itself never
    # attaches it -- see orchestrator.py's _hydrate_metadata docstring).
    gadget_1_hit = next(h for h in page.hits if h.id == "gadget-1")
    assert gadget_1_hit.metadata["category"] == "Peripherals"
    assert gadget_1_hit.metadata["rating"] == 4.5

    # gadget-1 has a near-identical query vector -> highest combined score.
    assert page.hits[0].id == "gadget-1"


def test_case_insensitive_override_actually_widens_the_match(gadgets_engine):
    """Without the override, category='Peripherals' would miss gadget-2
    (stored as 'peripherals', lowercase). Proves the custom stub named in
    the DoD text is genuinely wired into the live request path, not just
    unit-testable in isolation."""
    request = SearchRequest(
        lexical=LexicalQuery(),  # match-all lexical rule; filters do the narrowing
        filters={"category": "PERIPHERALS"},
    )

    page = gadgets_engine.search(request)

    assert {hit.id for hit in page.hits} == {"gadget-1", "gadget-2", "gadget-4"}


def test_range_and_contains_filters_compose_with_lexical_search(gadgets_engine):
    request = SearchRequest(
        lexical=LexicalQuery(mandatories=["office"]),
        filters={"rating": {"min": 4.0}, "tags": "office"},
    )

    page = gadgets_engine.search(request)

    # rating >= 4.0 keeps gadget-1/2 (excludes gadget-4 at 3.1); tags
    # contains 'office' keeps gadget-1/2/4 (excludes gadget-3) -- so the
    # filter stage narrows to {gadget-1, gadget-2}. Of those, only
    # gadget-1's TEXT actually mentions "office" ("...for office use.");
    # gadget-2's text ("mechanical keyboard with RGB lighting") does not,
    # so the lexical mandatories=["office"] rule excludes it.
    assert {hit.id for hit in page.hits} == {"gadget-1"}


def test_well_formed_query_with_no_matches_returns_empty_page_not_an_error(gadgets_engine):
    """'No results' is a normal outcome (app/api/errors.py), never an
    exception -- a perfectly valid, overly-strict filter combination."""
    request = SearchRequest(
        lexical=LexicalQuery(),
        filters={"category": "peripherals", "rating": {"min": 100.0}},
    )

    page = gadgets_engine.search(request)

    assert page.hits == []
    assert page.total_hits == 0
    assert page.total_pages == 0


def test_pagination_slices_the_ranked_result(gadgets_engine):
    request = SearchRequest(
        lexical=LexicalQuery(),  # match-all: every in-stock/out-of-stock gadget
        filters={},
        page=1,
        page_size=2,
    )
    page_1 = gadgets_engine.search(request)
    assert len(page_1.hits) == 2
    assert page_1.total_hits == 4
    assert page_1.total_pages == 2
    assert page_1.has_next is True

    page_2 = gadgets_engine.search(request.model_copy(update={"page": 2}))
    assert len(page_2.hits) == 2
    assert page_2.has_next is False
    assert page_2.has_previous is True

    # No overlap between pages, and together they cover the whole result.
    assert {h.id for h in page_1.hits} | {h.id for h in page_2.hits} == {
        "gadget-1", "gadget-2", "gadget-3", "gadget-4",
    }
    assert set(h.id for h in page_1.hits).isdisjoint(h.id for h in page_2.hits)


# ---------------------------------------------------------------------------
# Consistent error types (deliverable 3)
# ---------------------------------------------------------------------------


def test_unknown_filter_field_is_a_bad_query_error(gadgets_engine):
    request = SearchRequest(lexical=LexicalQuery(), filters={"not_a_real_field": "x"})
    with pytest.raises(BadQueryError, match="unknown filter field"):
        gadgets_engine.search(request)


def test_disabled_search_mode_is_a_bad_query_error(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _GADGETS_CONFIG_YAML.replace("enabled: true\n    multi_query_combination", "enabled: false\n    multi_query_combination")
    )
    from app.core.filtering import load_filters

    config, filters = load_filters(config_path)
    schema = config.to_metadata_schema()
    report = ingest_raw_records(_RAW_RECORDS, schema)
    engine = SearchEngine(config, filters, report.valid_documents)

    request = SearchRequest(semantic=[SemanticQuery(vector=[1.0, 0.0])])
    with pytest.raises(BadQueryError, match="search.semantic.enabled"):
        engine.search(request)


def test_semantic_request_without_embedding_provider_is_a_bad_config_error(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_GADGETS_CONFIG_YAML)
    from app.core.filtering import load_filters

    config, filters = load_filters(config_path)
    schema = config.to_metadata_schema()
    report = ingest_raw_records(_RAW_RECORDS, schema)
    engine = SearchEngine(config, filters, report.valid_documents)  # no embedding_provider

    request = SearchRequest(semantic=[SemanticQuery(vector=[1.0, 0.0])])
    with pytest.raises(BadConfigError, match="embedding_provider"):
        engine.search(request)


def test_malformed_config_surfaces_as_bad_config_error(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
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

    with pytest.raises(BadConfigError):
        SearchEngine.from_config_path(config_path, documents=[])
