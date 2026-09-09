"""
app/api/http.py

The missing wire: everything in `app/api/orchestrator.py` is an
in-process Python entry point (`SearchEngine.search(SearchRequest) ->
SearchResultPage`). Nothing before this module made that reachable over
HTTP, which means no frontend or external
client could ever call it -- there was no route, no request parsing,
no JSON response, no status-code mapping, despite `app/api/errors.py`
being explicitly designed around "these map to different HTTP status
codes" from day one.

This module closes that gap, generically -- it knows about
`SearchEngine`, `SearchRequest`, `SearchResultPage`, and the two
`SearchAPIError` subclasses, and NOTHING about any use case's field
names. A project wires it up with two lines in its own bootstrap:

    from app.api.http import create_search_blueprint
    app.register_blueprint(create_search_blueprint(engine), url_prefix="/api")

That gives the project these frontend-facing routes:

    GET  /api/health   -> {"status": "ok"}
    GET  /api/config   -> resolved branding, filter controls, capabilities,
                          and pagination limits
    GET  /api/facets   -> currently available filter values / date bounds
    POST /api/search   -> body is a JSON `SearchRequest`
                           (see app/api/request.py for the shape),
                           response is a JSON `SearchResultPage`
                           (see app/core/search/pagination/engine.py)
    GET  /api/documents/<id> -> full indexed text, metadata, and navigation URLs
    GET  /api/documents/<id>/source -> original file, only when a project
                                        supplies a source-file resolver

Status code mapping (per `app/api/errors.py`'s own stated intent):

    200  successful search (including zero-hit results -- see
         errors.py's "NO RESULTS is not an exception" section)
    400  malformed request: fails `SearchRequest` validation, or the
         orchestrator raises `BadQueryError`
    404  no route matches the request path at all
    405  the route exists but not for this HTTP method (e.g. `GET
         /search` instead of `POST`)
    500  the project's config/engine itself is broken
         (`BadConfigError`), or any other unexpected exception

EVERY response from routes wired through this module -- including the
404/405/etc. cases above, which Flask would otherwise render as HTML --
is JSON, with the same `{"error": {"type", "message"}}` shape. A
frontend calling `response.json()` should never hit an HTML page and
throw a parse error just because it mistyped a path or used the wrong
verb. `register_json_error_handlers()` is what makes this true; it is
called automatically by `create_http_app()`, and is exported separately for
a project that composes `create_search_blueprint()` into its own
existing Flask app (an app-level 404 has no matched blueprint, so a
blueprint-only `@errorhandler` can't catch it -- only an app-level one
can, which is why this is a separate opt-in function rather than baked
into the blueprint).

CORS: `create_http_app()` enables CORS by default (via `flask-cors`, an
optional dependency, part of the `http` extra) because the single most
common "the backend works in curl/Postman but the frontend can't reach
it" failure is a missing `Access-Control-Allow-Origin` header on a
cross-origin browser request -- the request never even reaches
`/search`; the browser blocks it before sending. The default is
permissive (`*`) since this API is typically read-only/public-document
search rather than authenticated; pass `cors_origins=` to restrict it
to specific frontend origin(s) in production. `create_search_blueprint()`
does NOT enable CORS by default (a project composing it into a larger
app may already have its own CORS policy) but accepts the same
`cors_origins` parameter to opt in explicitly.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from flask import Blueprint, Flask, jsonify, request as flask_request, send_file, url_for
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.api.errors import BadConfigError, BadQueryError
from app.api.orchestrator import SearchEngine
from app.api.request import SearchRequest
from app.core.schema.metadata_types import NormalizedDocument

logger = logging.getLogger("app.api.http")

# The use-case layer maps an indexed document to an original file. The HTTP
# layer never builds a filesystem path from a client-provided document ID.
SourceFileResolver = Callable[[NormalizedDocument], Optional[Path]]


def _error_response(status: int, error_type: str, message: str, *, details: Any = None):
    body: dict[str, Any] = {"error": {"type": error_type, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def register_json_error_handlers(app: Flask) -> None:
    """Make every error response from `app` JSON, not Flask's default
    HTML error pages -- including ones that never reach a view function
    at all (404 for an unmatched path, 405 for a matched path/wrong
    method, and any other werkzeug `HTTPException`), plus a last-resort
    handler for exceptions raised outside `/search`'s own try/except
    (e.g. in a `before_request` hook, or a different blueprint entirely).

    Idempotent to call more than once is NOT guaranteed (Flask raises if
    the same exception class is registered twice on the same app) -- if
    a project already has its own error handlers for `HTTPException` /
    `Exception`, call this before adding project-specific ones, or skip
    it and replicate the same JSON shape in its own handlers instead.
    """

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        error_type = (exc.name or "HTTPError").replace(" ", "")
        return _error_response(exc.code or 500, error_type, exc.description or exc.name or "")

    @app.errorhandler(Exception)
    def _handle_unexpected_exception(exc: Exception):
        logger.exception("unhandled exception outside the /search route")
        return _error_response(500, "InternalError", "an unexpected error occurred")


def _frontend_config_payload(engine: SearchEngine) -> dict[str, Any]:
    """Return the resolved, client-safe portion of a use-case configuration."""
    config = engine.config
    filters: list[dict[str, Any]] = []
    for name, override in sorted(config.frontend.filters.items(), key=lambda item: item[1].order):
        field = config.filters[name]
        filters.append(
            {
                "name": name,
                "label": override.label,
                "control": override.control,
                "order": override.order,
                "placeholder": override.placeholder,
                "type": field.type.value,
                "item_type": field.item_type.value if field.item_type is not None else None,
                "operation": field.operation,
                "required": field.required,
                "default": field.default,
            }
        )
    return {
        "branding": config.frontend.branding.model_dump(mode="json"),
        "labels": config.frontend.labels.model_dump(mode="json"),
        "filters": filters,
        "result_card_fields": config.frontend.result_card_fields,
        "search": engine.capabilities(),
        "pagination": {
            "default_page_size": config.search.pagination.default_page_size,
            "max_page_size": config.search.pagination.max_page_size,
        },
    }


def create_search_blueprint(
    engine: SearchEngine,
    name: str = "search_api",
    *,
    cors_origins: Optional[Union[str, Sequence[str]]] = None,
    source_file_resolver: Optional[SourceFileResolver] = None,
) -> Blueprint:
    """Build a Flask `Blueprint` exposing `engine` over HTTP.

    Generic on purpose: takes an already-fully-constructed
    `SearchEngine` (however the calling project built it --
    `SearchEngine.from_config_path()` or otherwise) and exposes exactly
    the two routes described in this module's docstring. Nothing here
    reads a use-case's config file, field names, or branding -- that
    stays entirely inside the project's own bootstrap, same as every
    other generic/custom boundary in this codebase.

    `cors_origins`: `None` (default) adds no CORS headers -- appropriate
    when composing this blueprint into an app that already has its own
    CORS policy. Pass `"*"` or a list of allowed origins to enable CORS
    for just this blueprint's routes (requires `flask-cors`; raises
    `RuntimeError` with an install hint if it isn't installed).

    `source_file_resolver` is an optional use-case adapter from an indexed
    document to its original file. When supplied, source URLs are included in
    search/document responses and ``GET /documents/<id>/source`` is enabled.
    The adapter owns path validation and access policy.
    """
    blueprint = Blueprint(name, __name__)

    if cors_origins is not None:
        try:
            from flask_cors import CORS
        except ImportError as exc:  # pragma: no cover - exercised via install docs, not tests
            raise RuntimeError(
                "cors_origins was given but flask-cors is not installed. "
                "Install it with: pip install '.[http]'"
            ) from exc
        CORS(blueprint, origins=cors_origins)

    @blueprint.get("/health")
    def health():  # pragma: no cover - trivial
        return jsonify({"status": "ok"})

    @blueprint.get("/config")
    def frontend_config():
        """Expose the resolved UI contract without leaking server config."""
        return jsonify(_frontend_config_payload(engine))

    @blueprint.get("/facets")
    def facets():
        # Only advertised controls are returned. A backend-only filter stays
        # callable through POST /search but is not accidentally exposed in UI.
        fields = list(engine.config.frontend.filters)
        return jsonify({"filters": engine.filter_facets(fields)})

    def _document_url(document_id: str) -> str:
        return url_for(f"{blueprint.name}.document", document_id=document_id)

    def _source_url(document: NormalizedDocument) -> Optional[str]:
        if source_file_resolver is None:
            return None
        result = url_for(f"{blueprint.name}.document_source", document_id=document.id)
        page = document.metadata.get("source_page")
        # PDF viewers understand #page=N. Fragments stay client-side and do
        # not affect the server's source-file access controls.
        return f"{result}#page={page}" if isinstance(page, int) and page > 0 else result

    def _document_payload(document: NormalizedDocument, *, include_text: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": document.id,
            "metadata": document.model_dump(mode="json")["metadata"],
            "document_url": _document_url(document.id),
            "source_url": _source_url(document),
        }
        if include_text:
            payload["text"] = document.text
        return payload

    @blueprint.get("/documents/<path:document_id>")
    def document(document_id: str):
        indexed_document = engine.get_document(document_id)
        if indexed_document is None:
            return _error_response(404, "DocumentNotFound", "document was not found")
        return jsonify(_document_payload(indexed_document, include_text=True))

    @blueprint.get("/documents/<path:document_id>/source")
    def document_source(document_id: str):
        indexed_document = engine.get_document(document_id)
        if indexed_document is None:
            return _error_response(404, "DocumentNotFound", "document was not found")
        if source_file_resolver is None:
            return _error_response(404, "SourceUnavailable", "source file is not available")
        try:
            source_path = source_file_resolver(indexed_document)
        except (OSError, ValueError) as exc:
            logger.warning("source resolver rejected document %r: %s", document_id, exc)
            source_path = None
        if not isinstance(source_path, Path) or not source_path.is_file():
            return _error_response(404, "SourceUnavailable", "source file is not available")
        return send_file(source_path, conditional=True)

    @blueprint.post("/search")
    def search():
        payload = flask_request.get_json(silent=True)
        if payload is None:
            return _error_response(
                400, "BadQueryError", "request body must be valid JSON"
            )

        try:
            search_request = SearchRequest.model_validate(payload)
        except ValidationError as exc:
            return _error_response(
                400,
                "BadQueryError",
                "request body does not match the SearchRequest schema",
                details=exc.errors(include_url=False, include_context=False),
            )

        try:
            result_page = engine.search(search_request)
        except BadQueryError as exc:
            return _error_response(400, "BadQueryError", str(exc))
        except BadConfigError as exc:
            logger.error("search request failed due to BadConfigError: %s", exc)
            return _error_response(
                500,
                "BadConfigError",
                "this project's search engine is misconfigured",
            )
        except Exception:  # noqa: BLE001 - deliberate top-level HTTP boundary
            logger.exception("unexpected error handling /search")
            return _error_response(
                500, "InternalError", "an unexpected error occurred"
            )

        body = result_page.model_dump(mode="json")
        for hit in body["hits"]:
            indexed_document = engine.get_document(hit["id"])
            # Defensive fallback: a provider cannot make an otherwise valid
            # search response fail merely because it returned a stale ID.
            hit["document_url"] = (
                _document_url(indexed_document.id) if indexed_document is not None else None
            )
            hit["source_url"] = _source_url(indexed_document) if indexed_document is not None else None
        return jsonify(body)

    return blueprint


def create_http_app(
    engine: SearchEngine,
    *,
    url_prefix: str = "/api",
    cors_origins: Optional[Union[str, Sequence[str]]] = "*",
    source_file_resolver: Optional[SourceFileResolver] = None,
) -> Flask:
    """Convenience factory for the common case of "just give me a Flask
    app for this one engine." Registers `register_json_error_handlers()`
    automatically (so 404/405/anything unexpected are JSON, not HTML)
    and enables CORS by default (`cors_origins="*"`) so a frontend on a
    different origin works out of the box -- pass `cors_origins=None`
    to disable, or a specific origin/list to restrict it.

    `source_file_resolver` optionally enables original-file delivery for
    document records. It belongs in a use case's custom layer, where source
    paths and authorization can be validated safely.

    Named `create_http_app`, not `create_app`, deliberately: this
    package (`app/`) already has a zero-argument `create_app()` at
    `app/__init__.py` -- the legacy artisan app's bootstrap (loads
    `data_loader`, wires `app/routes.py`, needs flask/flask_cors and,
    transitively, faiss/sentence-transformers). Reusing the same name
    for a completely different, generic-engine Flask app one level down
    (`app.api.http.create_app`) would be a real footgun: `from app
    import create_app` and `from app.api.http import create_app` would
    silently return two unrelated apps.

    A project with more than one engine, or that needs to compose this
    blueprint into a larger app (e.g. alongside the legacy artisan app
    in `app/routes.py`), should call `create_search_blueprint()` and
    `register_json_error_handlers()` directly instead of this function.
    """
    app = Flask(__name__)
    # Arabic (and any other non-ASCII) text in metadata/snippets should
    # round-trip as readable UTF-8 in the raw JSON response, not
    # \uXXXX escapes -- matches the same setting and reasoning already
    # used by the legacy app's create_app() (app/__init__.py) for the
    # same underlying Arabic-language document corpora.
    app.config["JSON_AS_ASCII"] = False

    # Optional gzip compression for potentially large paginated result
    # sets -- same optional, best-effort pattern as the legacy app's
    # create_app(): only enabled if flask-compress happens to be
    # installed, silently skipped otherwise. Not part of any
    # dependency group here since it's fully optional either way.
    try:
        from flask_compress import Compress

        Compress(app)
    except ImportError:
        pass

    register_json_error_handlers(app)
    app.register_blueprint(
        create_search_blueprint(
            engine,
            cors_origins=cors_origins,
            source_file_resolver=source_file_resolver,
        ),
        url_prefix=url_prefix,
    )
    return app
