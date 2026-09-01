"""
app/api/observability.py

Deliberately minimal -- this is NOT a metrics/tracing system, just the
one small piece every future project would otherwise reinvent
inconsistently : one logger, one context manager that logs a
stage-started / stage-finished pair with a duration and a small
structured payload, and one helper for the "no results" non-error event
described in `app/api/errors.py`.

All log records go through the standard library `logging` module under
the `"app.api"` logger name, with structured fields passed via `extra=`
rather than baked into the message string -- so a project that wants
real structured logging (JSON lines, an ingest pipeline, ...) can attach
its own `logging.Formatter`/handler without this module changing at all.
This module only decides WHAT to log and WHEN, never HOW it is rendered
or shipped.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("app.api")


@contextmanager
def log_stage(stage: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Log `"{stage}.started"` on entry and `"{stage}.finished"` (or
    `"{stage}.failed"`, on an exception) on exit, with a duration and
    whatever structured fields the caller supplies.

    Yields a plain `dict` the caller can mutate to add fields that are
    only known AFTER the stage runs (e.g. result counts) -- those are
    merged into the "finished" log record's `extra`, so the request's
    input fields and its output fields end up on the SAME log line
    rather than split across two records a reader has to correlate by
    hand.

    Usage::

        with log_stage("filtering", request_fields=sorted(request.filters)) as out:
            candidates = self._apply_filters(request.filters)
            out["candidate_count"] = len(candidates)
    """
    result: dict[str, Any] = {}
    started_at = time.monotonic()
    logger.info("%s.started", stage, extra={"stage": stage, **fields})
    try:
        yield result
    except Exception:
        duration_ms = round((time.monotonic() - started_at) * 1000, 3)
        logger.exception(
            "%s.failed",
            stage,
            extra={"stage": stage, "duration_ms": duration_ms, **fields},
        )
        raise
    else:
        duration_ms = round((time.monotonic() - started_at) * 1000, 3)
        logger.info(
            "%s.finished",
            stage,
            extra={"stage": stage, "duration_ms": duration_ms, **fields, **result},
        )


def log_no_results(**fields: Any) -> None:
    """The one deliberately-non-exception "outcome" event described in
    `app/api/errors.py`: a well-formed request that legitimately matched
    zero documents. Logged at INFO (not WARNING/ERROR) -- an empty result
    set is a normal outcome, not a problem -- so it's visible to anyone
    watching logs/metrics without being mistaken for a failure.
    """
    logger.info("search.no_results", extra={"stage": "search", **fields})
