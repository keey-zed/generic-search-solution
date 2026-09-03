# HTTP Layer (`app/api/http.py`)

## Why this exists

"Common API/orchestrator" (`app/api/orchestrator.py`) built a
single Python entry point, `SearchEngine.search(SearchRequest) ->
SearchResultPage`. That is an in-process API, not a network one — until
this module, nothing translated it into something an external client
(a frontend, `curl`, a CLI in another language) could actually call.
`app/api/errors.py` was written from day one assuming a caller "an HTTP
route, a CLI, a test" would exist, and describing which errors "map to
different HTTP status codes" — but no route existed yet. This module is
that route.

It intentionally stays inside `app/api/`, not `app/custom/`: it knows
about the generic `SearchEngine`/`SearchRequest`/`SearchResultPage`/
`SearchAPIError` types and nothing about any use case's field names,
same boundary as every other generic module in this repo (see
`tests/test_no_domain_vocabulary.py`).

## Wiring it into a project

```python
from app.api import SearchEngine
from app.api.http import create_http_app

engine = SearchEngine.from_config_path("app/custom/<use_case>/config.yaml", documents, ...)
app = create_http_app(engine)
app.run()
```

Or, to compose it into an existing Flask app (e.g. alongside another
blueprint) instead of getting a whole app for free:

```python
from app.api.http import create_search_blueprint

app.register_blueprint(create_search_blueprint(engine), url_prefix="/api")
```

## Endpoints

### `GET /health`

Returns `{"status": "ok"}`, always `200`. For a frontend or load
balancer to check the process is up before assuming `/search` will
work.

### `POST /search`

Request body: a JSON object matching `SearchRequest`
(`app/api/request.py`) — `semantic`, `lexical`, `filters`, `page`,
`page_size`. Example:

```json
{
  "lexical": {"first_of": ["taxation", "procurement"]},
  "filters": {"document_type": "Decree"},
  "page": 1
}
```

Response body on success (`200`): a JSON `SearchResultPage`
(`app/core/search/pagination/engine.py`) — `hits`, `page`, `page_size`,
`total_hits`, `total_pages`, `has_previous`, `has_next`.

## Status code mapping

| Status | When | Body shape |
|---|---|---|
| `200` | Search ran, including zero hits (per `errors.py`'s "NO RESULTS is not an exception") | `SearchResultPage` |
| `400` | Body isn't valid JSON, fails `SearchRequest` validation (e.g. neither `semantic` nor `lexical` given, wrong types), or the orchestrator raises `BadQueryError` (unknown filter field, disabled search mode, bad page number, ...) | `{"error": {"type": "BadQueryError", "message": "...", "details"?: [...]}}` |
| `404` | No route matches the request path | `{"error": {"type": "NotFound", "message": "..."}}` |
| `405` | The route exists, but not for this HTTP method (e.g. `GET /search`) | `{"error": {"type": "MethodNotAllowed", "message": "..."}}` |
| `500` | The orchestrator raises `BadConfigError` (the project's own config/engine is broken — not the requester's fault), or any other unexpected exception | `{"error": {"type": "BadConfigError" \| "InternalError", "message": "..."}}` |

**Every** response, including 404/405 and anything else werkzeug would
otherwise render as an HTML error page, comes back as JSON with this
same `{"error": {"type", "message"}}` shape. That's what
`register_json_error_handlers()` does — a frontend calling
`response.json()` should never hit an HTML page and get a parse error
just because it mistyped a path or used the wrong verb.

`register_json_error_handlers()` is called automatically by
`create_http_app()`. A project that instead composes `create_search_blueprint()`
into its own existing Flask app should call
`register_json_error_handlers(app)` itself if it wants the same
guarantee — a blueprint-level `@errorhandler` can't catch a 404 for a
path that never matched any blueprint, only an app-level handler can.

`500` responses never include exception internals in the body — only a
generic message. Full detail goes to the `app.api.http` / `app.api`
loggers (`logger.exception(...)`), consistent with the rest of the
codebase's observability posture (`app/api/observability.py`).

## CORS

The single most common "the backend works fine in curl/Postman but the
frontend can't reach it" failure is a missing
`Access-Control-Allow-Origin` header: the browser blocks the request
before it ever reaches `/search`, and it can look indistinguishable
from a backend bug to whoever is debugging the frontend.

`create_http_app()` enables CORS by default (`cors_origins="*"`, via the
optional `flask-cors` dependency — part of the `http` extra). Pass
`cors_origins=None` to disable it, or a specific origin / list of
origins (e.g. `cors_origins="https://my-frontend.example.com"`) to
restrict it once you know your production frontend's origin.

`create_search_blueprint()` does **not** enable CORS by default —
composing it into a larger app shouldn't silently impose a CORS policy
that app didn't ask for — but accepts the same `cors_origins` parameter
to opt in explicitly for just this blueprint's routes.

## Relationship to the legacy app's own HTTP layer

`app/routes.py` + `app/__init__.py`'s `create_app()` already have
extensive HTTP handling — but that's the **pre-factory, "artisan" app**
this whole codebase is meant to replace (see the architecture doc's
§1): hardcoded, per-use-case routes (`/search-advanced`,
`/filters/books`, `/admin/books/summary`, ...) coupled to global
mutable state (`data_loader.chunks`), with two independently-duplicated
pagination/response-building code paths and inconsistent error shapes
across routes. It is kept for reference only and is not imported by
`app/core`, `app/api`, or `app/custom` (verified —
`tests/test_no_domain_vocabulary.py` and a plain `grep` both confirm
no cross-import in either direction). `app/api/http.py` is the first
HTTP surface for the *generic* engine, not a duplicate of that file.

Two things were still worth carrying over from it, though, since they
reflect real operational needs of this project's data (Arabic legal
text, potentially large result sets), not artisan-app-specific design:

- `app.config["JSON_AS_ASCII"] = False` — otherwise Arabic (or other
  non-ASCII) text in a hit's metadata/snippet serializes as `\uXXXX`
  escapes. Still valid JSON, just unreadable without decoding.
- Optional `flask-compress` gzip, enabled only if installed
  (`try/except ImportError`, matching the legacy app's own pattern
  exactly) — not a hard dependency either way.

One naming collision was caught and fixed in the process: the legacy
`app/__init__.py` already defines a zero-argument `create_app()`.
Naming this module's convenience factory the same thing would have
meant `from app import create_app` and `from app.api.http import
create_app` silently returning two unrelated Flask apps. It's named
`create_http_app()` instead.

`SearchRequest.semantic` still expects **pre-computed vectors**
(`SemanticQuery.vector`), not natural-language query text. This module
does not add a text-to-embedding step at the HTTP boundary — that
remains a project-level, model-serving concern, per the same reasoning
`docs/pilot-notes.md` §1 already recorded: query-time embedding is
orthogonal to filtering/ranking, and belongs in a project's own
bootstrap/route wrapper (or, if a second project independently needs
the same thing, that repetition is the actual signal to add a generic
`QueryEmbedder` seam here — not something to guess at now).

Practically: a frontend that wants to let a user type a natural-
language query needs a small project-specific step — call an embedding
model, then send the resulting vector(s) as `semantic: [{"vector":
[...]}, ...]` — either client-side or via a thin wrapper route in the
project's own bootstrap. This is a real, known gap for the frontend to solve,
not something this HTTP layer silently papers over.
