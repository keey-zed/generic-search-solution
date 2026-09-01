"""
app/api/request.py
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.search.lexical import LexicalQuery
from app.core.search.semantic import SemanticQuery


class SearchRequest(BaseModel):
    """One request to `SearchEngine.search()` (`app/api/orchestrator.py`).

    At least one of `semantic` or `lexical` must be given -- a request
    with neither has nothing to search for (`filters` alone narrows a
    candidate set but is not itself a query; see source doc §3 vs §2).
    This is intentionally enforced here, at the request's own boundary,
    rather than deep inside the orchestrator, so a malformed request is
    rejected the moment it's constructed either way (the orchestrator's
    `BadQueryError` message wraps this in end-user-facing language, but
    the shape is invalid before the orchestrator gets involved).
    """

    model_config = ConfigDict(extra="forbid")

    semantic: list[SemanticQuery] = Field(
        default_factory=list,
        description=(
            "Zero or more semantic queries. Empty means 'no semantic "
            "search for this request' -- not an error by itself, as "
            "long as `lexical` is given instead."
        ),
    )
    lexical: Optional[LexicalQuery] = Field(
        default=None,
        description=(
            "A boolean lexical rule (first_of/mandatories), or None for "
            "'no lexical search for this request.' Note this is "
            "different from `LexicalQuery()` with both fields empty, "
            "which IS a valid rule meaning 'match every candidate' -- "
            "None here means the lexical stage does not run at all."
        ),
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "field_name -> filter params, for any subset of the "
            "fields declared under this project's config.yaml `filters:` "
            "block. A field name not declared in the loaded config is a "
            "BadQueryError, raised by the orchestrator (not here, since "
            "validating that requires the loaded config, which this "
            "model doesn't have access to)."
        ),
    )
    page: int = Field(default=1, ge=1)
    page_size: Optional[int] = Field(
        default=None,
        gt=0,
        description="None uses the project's config.yaml search.pagination.default_page_size.",
    )

    @model_validator(mode="after")
    def at_least_one_query_mode(self) -> "SearchRequest":
        if not self.semantic and self.lexical is None:
            raise ValueError(
                "a SearchRequest must provide at least one of `semantic` "
                "(one or more queries) or `lexical` (a boolean rule) -- "
                "`filters` alone narrows a candidate set but is not a query"
            )
        return self
