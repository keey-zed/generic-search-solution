"""
app/core/search/lexical/engine.py

The public entry point for lexical retrieval, mirroring
`app/core/search/semantic/engine.py`'s shape (`SemanticQuery`,
`semantic_search`) for its lexical counterpart (`LexicalQuery`,
`lexical_search`).

Generic-core rule: nothing here knows what a "term" means beyond a
non-blank string, and this module's only opinion on matching is the
default `contains_predicate` (plain, case-configurable substring
matching) -- a project needing exact-match or fuzzy matching supplies its
own `TermPredicate`-shaped callable instead; `lexical_search()` never
needs to change to support that (see `boolean_expr.py`'s `TermPredicate`).
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

from app.core.schema.search_hit import SearchHit
from app.core.search.lexical.boolean_expr import TermPredicate
from app.core.search.lexical.query import LexicalQuery

# Lexical matches always match on a document's main text content -- there
# is no per-field notion of "which metadata field matched" here (that's a
# metadata-filter concept, owned by the generic filtering framework, not
# this module). Kept as a module-level constant, same reasoning as
# semantic/engine.py's `_SEMANTIC_MATCHED_FIELDS`.
_LEXICAL_MATCHED_FIELDS = ["text"]


def contains_predicate(text: str, *, case_sensitive: bool = False) -> TermPredicate:
    """The default `TermPredicate`: plain substring containment of a term
    within `text`.

    Case-insensitive by default (`case_sensitive=False`) -- documented
    here as this module's default rather than left implicit, per the
    roadmap's note that a contains-style match needs "a documented
    case-sensitivity default."
    """
    haystack = text if case_sensitive else text.casefold()

    def predicate(term: str) -> bool:
        needle = term if case_sensitive else term.casefold()
        return needle in haystack

    return predicate


def lexical_search(
    documents: Iterable[Tuple[str, str]],
    rule: LexicalQuery,
    *,
    case_sensitive: bool = False,
) -> List[SearchHit]:
    """Evaluate `rule` against every `(id, text)` pair in `documents` and
    return a `List[SearchHit]` for every one that matches.

    Parameters
    ----------
    documents:
        An iterable of `(document_id, text)` pairs -- the candidate set
        to scan. Narrowing this set (e.g. to documents that already
        passed metadata filters) is the caller's job, not this
        function's; `lexical_search` itself has no notion of "the whole
        corpus" versus "a filtered subset."
    rule:
        A `LexicalQuery` (`first_of`/`mandatories`, possibly grouped).
        An empty/undefined rule matches every document -- see
        `LexicalQuery.to_boolean_expr()`.
    case_sensitive:
        Passed straight to `contains_predicate`. Pass a different
        `TermPredicate` directly to `expr.evaluate()` (bypassing this
        function) for matching strategies other than substring
        containment.

    Notes
    -----
    Boolean lexical matching has no inherent notion of relevance
    ranking, so every returned `SearchHit.score` is `None` -- exactly the
    "not applicable" case `SearchHit.score`'s docstring describes, never
    a stand-in for zero relevance. Results are sorted by `id` ascending
    so output is deterministic regardless of `documents`' iteration
    order.
    """
    expr = rule.to_boolean_expr()

    matched_ids: List[str] = []
    for doc_id, text in documents:
        predicate = contains_predicate(text, case_sensitive=case_sensitive)
        if expr.evaluate(predicate):
            matched_ids.append(doc_id)

    matched_ids.sort()

    return [
        SearchHit(id=doc_id, score=None, matched_fields=list(_LEXICAL_MATCHED_FIELDS))
        for doc_id in matched_ids
    ]
