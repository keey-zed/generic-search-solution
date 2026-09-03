"""
tests/test_http_api.py

Proves `app/api/http.py` actually closes the gap it claims to close:
that a client (a frontend, a CLI, `curl`) can reach a fully-built
`SearchEngine` over HTTP, with no use-case-specific code in the HTTP
layer itself. Reuses the exact `legal_pilot` construction from
`tests/test_pilot_definition_of_done.py` rather than a fake engine, so
this is an end-to-end proof through the real config/filters/ingestion
stack, not just a mock of `SearchEngine.search()`.
"""
from __future__ import annotations

import random

import pytest

from app.api import SearchEngine
from app.api.http import create_http_app
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord


def _fake_embedding(seed: int, dim: int = 4) -> Embedding:
    rng = random.Random(seed)
    return Embedding(vector=[rng.uniform(-1, 1) for _ in range(dim)], model_id="fake-http-test-embedder-v0")


@pytest.fixture()
def pilot_engine() -> SearchEngine:
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


@pytest.fixture()
def client(pilot_engine: SearchEngine):
    app = create_http_app(pilot_engine)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_health_endpoint_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_search_with_lexical_query_returns_200_and_search_result_page_shape(client):
    response = client.post(
        "/api/search",
        json={"lexical": {"first_of": ["taxation", "procurement", "decree"]}},
    )
    assert response.status_code == 200
    body = response.get_json()
    # SearchResultPage's own field set (app/core/search/pagination/engine.py) --
    # a frontend integrating against this endpoint needs exactly these keys.
    assert set(body.keys()) == {
        "hits",
        "page",
        "page_size",
        "total_hits",
        "total_pages",
        "has_previous",
        "has_next",
    }
    assert isinstance(body["hits"], list)


def test_search_with_filters_and_lexical_narrows_results(client):
    baseline = client.post(
        "/api/search", json={"lexical": {"first_of": []}}
    ).get_json()
    filtered = client.post(
        "/api/search",
        json={
            "lexical": {"first_of": []},
            "filters": {"document_type": "Decree"},
        },
    ).get_json()
    assert filtered["total_hits"] <= baseline["total_hits"]


def test_search_with_no_query_mode_is_a_400_bad_query_error(client):
    """SearchRequest's own validator rejects a request with neither
    `semantic` nor `lexical` -- this must surface as 400, not 500."""
    response = client.post("/api/search", json={"filters": {}})
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["type"] == "BadQueryError"


def test_search_with_unknown_filter_field_is_a_400_bad_query_error(client):
    response = client.post(
        "/api/search",
        json={
            "lexical": {"first_of": []},
            "filters": {"not_a_real_field": "x"},
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "BadQueryError"


def test_search_with_malformed_json_body_is_a_400(client):
    response = client.post(
        "/api/search", data="not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "BadQueryError"


def test_search_with_wrong_shaped_body_is_a_400_with_validation_details(client):
    response = client.post("/api/search", json={"page": "not-an-int"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["type"] == "BadQueryError"
    assert "details" in body["error"]


def test_search_semantic_query_path_returns_200(client):
    response = client.post(
        "/api/search",
        json={"semantic": [{"vector": [0.1, 0.2, 0.3, 0.4]}]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["page"] == 1


def test_unknown_route_is_404_json_not_html(client):
    """Flask's default 404 is an HTML page -- a frontend calling
    `response.json()` on that would throw a parse error instead of
    getting a clean error object. register_json_error_handlers()
    (wired in automatically by create_http_app) must prevent that."""
    response = client.get("/api/this-route-does-not-exist")
    assert response.status_code == 404
    assert response.content_type.startswith("application/json")
    body = response.get_json()
    assert body["error"]["type"] == "NotFound"


def test_wrong_method_is_405_json_not_html(client):
    """GET /api/search: the route exists but only accepts POST."""
    response = client.get("/api/search")
    assert response.status_code == 405
    assert response.content_type.startswith("application/json")
    body = response.get_json()
    assert body["error"]["type"] == "MethodNotAllowed"


def test_cors_headers_present_by_default_on_create_http_app(client):
    """create_http_app() defaults to permissive CORS specifically so a
    frontend running on a different origin (e.g. a dev server on
    localhost:3000) isn't silently blocked by the browser -- the most
    common 'works in curl, fails in the browser' failure mode."""
    response = client.post(
        "/api/search",
        json={"lexical": {"first_of": []}},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    allow_origin = response.headers.get("Access-Control-Allow-Origin")
    assert allow_origin in ("*", "http://localhost:3000")


def test_cors_preflight_request_is_answered(client):
    response = client.options(
        "/api/search",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code in (200, 204)
    assert "Access-Control-Allow-Origin" in response.headers


def test_create_search_blueprint_without_cors_origins_has_no_cors_headers(pilot_engine):
    """create_search_blueprint() alone (no cors_origins) adds no CORS
    headers -- composing it into a larger app must not silently impose
    a CORS policy that app didn't ask for."""
    from flask import Flask
    from app.api.http import create_search_blueprint

    app = Flask(__name__)
    app.register_blueprint(create_search_blueprint(pilot_engine), url_prefix="/api")
    with app.test_client() as bare_client:
        response = bare_client.post(
            "/api/search",
            json={"lexical": {"first_of": []}},
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert "Access-Control-Allow-Origin" not in response.headers


def test_create_search_blueprint_can_opt_into_cors_explicitly(pilot_engine):
    from flask import Flask
    from app.api.http import create_search_blueprint

    app = Flask(__name__)
    app.register_blueprint(
        create_search_blueprint(pilot_engine, cors_origins="https://example.com"),
        url_prefix="/api",
    )
    with app.test_client() as scoped_client:
        response = scoped_client.post(
            "/api/search",
            json={"lexical": {"first_of": []}},
            headers={"Origin": "https://example.com"},
        )
        assert response.headers.get("Access-Control-Allow-Origin") == "https://example.com"


def test_create_http_app_does_not_ascii_escape_non_latin_text(pilot_engine):
    """app/__init__.py's legacy create_app() sets JSON_AS_ASCII = False
    for the same corpora (Arabic legal/Bulletin Officiel text) this
    engine serves -- create_http_app() must carry that setting so a
    response's Arabic metadata/snippets are readable UTF-8, not
    \\uXXXX escapes."""
    app = create_http_app(pilot_engine)
    assert app.config["JSON_AS_ASCII"] is False
