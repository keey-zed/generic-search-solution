"""
app/api/errors.py

Three kinds of thing can go wrong on a request to the common API
(`app/api/orchestrator.py`), and a caller (an HTTP route, a CLI, a test)
needs to be able to tell them apart -- they map to different HTTP status
codes and different remediation:

  1. BAD CONFIG   -- the PROJECT is misconfigured: config.yaml failed to
                      load/validate, or a `custom_filters` override
                      doesn't match its declared operation. Not the
                      requester's fault; typically a 500-class problem a
                      developer must fix before anyone can query at all.
  2. BAD QUERY     -- the REQUEST is malformed given an otherwise-valid
                      config: an unknown filter field name, a filter
                      value the field's type rejects, an out-of-range
                      page number, asking for semantic search when
                      `search.semantic.enabled` is false, or providing
                      neither a semantic nor a lexical query at all.
                      Typically a 400-class problem -- the requester's
                      input, not the server's state, is wrong.
  3. NO RESULTS    -- deliberately NOT an exception. A query that is
                      perfectly well-formed and legitimately matches
                      nothing (e.g. filters that are individually valid
                      but jointly too strict) is a normal, successful
                      outcome -- `SearchResultPage(hits=[], total_hits=0,
                      ...)` -- not a failure. Modeling "no results" as an
                      error would force every well-formed empty search to
                      be handled via exception flow, which is exactly the
                      kind of control-flow-via-exceptions antipattern the
                      rest of this codebase avoids (see e.g.
                      `Filter.apply`'s own docstring: "must never raise
                      for 'nothing matched'"). Instead, "no results" gets
                      its own STRUCTURED LOG event (see
                      `app/api/observability.py`) so it's still visible
                      to whoever is watching logs/metrics, without
                      forcing API callers to wrap every search in a
                      try/except for a non-error outcome.

Both real error classes inherit from one `SearchAPIError` base so a
caller who doesn't need the distinction (e.g. a top-level HTTP error
handler that just wants "this request failed") can catch one type,
while a caller who DOES need the distinction (to pick a status code) can
catch the specific subclass.
"""
from __future__ import annotations


class SearchAPIError(Exception):
    """Base class for every error the common API layer raises. Never
    raised directly -- always one of the subclasses below."""


class BadConfigError(SearchAPIError):
    """The project's configuration (config.yaml, and/or its
    `custom_filters` overrides) could not be loaded or is internally
    inconsistent -- not something a well-formed request can work around.

    Typically wraps `app.core.config.loader.ConfigLoadError` /
    `app.core.filtering.FilterError` raised while building a
    `SearchEngine`, but is also raised directly for orchestrator-level
    setup problems (e.g. a semantic query was requested but no
    `embedding_provider` was ever configured for this engine).
    """


class BadQueryError(SearchAPIError):
    """The request itself is malformed, given an otherwise-valid config:
    an unknown filter field name, a filter value rejected by the field's
    type, an invalid page/page_size, requesting a search mode
    (`semantic`/`lexical`) the config has disabled, or requesting neither
    mode at all.

    Typically wraps a lower-level `app.core.filtering.FilterError` or a
    `ValueError` from `paginate()`/`semantic_search()`, re-raised as this
    one consistent type so a caller never needs to know which internal
    module actually detected the problem.
    """
