"""
app/core/search/lexical/boolean_expr.py

A generic boolean-expression tree for evaluating lexical match
rules (`first_of`, `mandatories`, and the grouped-mandatories case)
against a document.

Deliberately built as a small recursive tree with one `evaluate()` method
per node type (`Term`, `And`, `Or`, `MatchAll`), rather than a
special-cased loop over "OR of ANDs" -- the roadmap is explicit that a
future "NOT" or deeper nesting must not require a rewrite. With this
shape, adding NOT later is exactly:

    class Not(BooleanExpr):
        child: BooleanExpr
        def evaluate(self, predicate):
            return not self.child.evaluate(predicate)

...one new class, zero changes to `Term`/`And`/`Or`/`MatchAll` or to
whatever calls `.evaluate()`. Deeper nesting (e.g. `And` inside `Or`
inside `And`) already works today with no special-casing at all, because
`children` is typed as `BooleanExpr`, not `Term` -- see `And`/`Or` below.

Generic-core rule: this module knows nothing about what a "term" means
(no field names, no domain vocabulary, no assumption about *how* a term
is matched against a document) -- it only knows how to combine `bool`
results according to boolean logic. What "matches" means is supplied by
the caller as a `TermPredicate` callback (see `query.py` / `engine.py`
for the concrete text-substring predicate used by lexical search).
"""
from __future__ import annotations

from typing import Callable, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Given one term, return whether the current document/candidate matches
# it. Supplied by whoever calls `evaluate()` -- this module has no
# opinion on what "matches" means (substring? exact? fuzzy?).
TermPredicate = Callable[[str], bool]


class BooleanExpr(BaseModel):
    """Base class for one node in a boolean-expression tree.

    Every subclass implements `evaluate(predicate)` and nothing else --
    that single method is the entire contract a new node type must
    satisfy, which is what keeps extending this tree (NOT, XOR, deeper
    nesting, ...) a matter of adding a subclass rather than touching
    existing ones or the code that walks the tree.
    """

    model_config = ConfigDict(extra="forbid")

    def evaluate(self, predicate: TermPredicate) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class Term(BooleanExpr):
    """Leaf node: a single literal term/expression/keyword.

    Evaluates to whatever `predicate(term)` returns -- this class has no
    idea whether that's a substring check, an exact match, or something
    fuzzier; that decision belongs entirely to the caller-supplied
    predicate (see `engine.py::contains_predicate` for the one this
    module ships with).
    """

    term: str = Field(..., min_length=1)

    @field_validator("term")
    @classmethod
    def term_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("term must not be blank or whitespace-only")
        return v

    def evaluate(self, predicate: TermPredicate) -> bool:
        return bool(predicate(self.term))


class And(BooleanExpr):
    """True iff every child evaluates to True.

    This is `mandatories`'s flat case (§2: `term1 AND term2 AND term3`,
    modeled as `And(children=[Term(...), Term(...), Term(...)])`) and also
    the building block for one group inside the grouped-mandatories case
    (`(A1 AND A2 AND A3)`).
    """

    children: List[BooleanExpr] = Field(..., min_length=1)

    def evaluate(self, predicate: TermPredicate) -> bool:
        return all(child.evaluate(predicate) for child in self.children)


class Or(BooleanExpr):
    """True iff at least one child evaluates to True.

    This is `first_of` (§2: `term1 OR term2 OR term3`, modeled as
    `Or(children=[Term(...), Term(...), Term(...)])`) and ALSO the outer
    combinator for the grouped-mandatories case
    (`(A1∧A2∧A3) OR (B1∧B2∧B3)`) -- both are exactly `Or` over a list of
    children, one over `Term`s and one over `And`s. There is no
    special-cased "grouped mandatories" node; `query.py`'s
    `build_mandatories_expr()` builds exactly
    `Or(children=[And(children=[Term(...), ...]), And(children=[Term(...), ...])])`
    for the grouped case, reusing this same class.
    """

    children: List[BooleanExpr] = Field(..., min_length=1)

    def evaluate(self, predicate: TermPredicate) -> bool:
        return any(child.evaluate(predicate) for child in self.children)


class MatchAll(BooleanExpr):
    """Always evaluates to True, regardless of the predicate.

    This is the "empty/undefined rule" case: a lexical query with no `first_of` and no `mandatories` at
    all must match every candidate, not raise or silently reject them --
    see `query.py::LexicalQuery.to_boolean_expr()`, which returns this
    node when both are absent (or explicitly empty).
    """

    def evaluate(self, predicate: TermPredicate) -> bool:
        return True
