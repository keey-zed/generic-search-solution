"""
app/core/search/lexical/query.py

The `first_of` / `mandatories` rule shape a use-case config declares, and the builder functions that
turn it into the generic `BooleanExpr` tree from `boolean_expr.py`.

    first_of     = [term1, term2, term3]                     -> Or(Term, Term, Term)
    mandatories  = [term1, term2, term3]                     -> And(Term, Term, Term)
    mandatories  = [[A1, A2, A3], [B1, B2, B3]]               -> Or(And(A1,A2,A3), And(B1,B2,B3))
    neither given (or both empty)                             -> MatchAll()

Nothing in this module knows what a "term" IS beyond a non-blank string
-- how a term is matched against a document (substring? exact? fuzzy?)
is `engine.py`'s job, not this one's.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.search.lexical.boolean_expr import And, BooleanExpr, MatchAll, Or, Term


def build_first_of_expr(first_of: Sequence[str]) -> BooleanExpr:
    """`first_of = [term1, term2, term3]` -> `term1 OR term2 OR term3`.

    Raises if `first_of` is empty -- callers that want "no constraint"
    should omit the rule entirely (or pass an empty/None value into
    `LexicalQuery`, see `to_boolean_expr()` below) rather than pass an
    empty list here; an *explicit* empty OR-list has no sensible meaning
    of its own to fall back on inside this function.
    """
    terms = list(first_of)
    if not terms:
        raise ValueError(
            "first_of must contain at least one term; omit the rule "
            "entirely (or pass None/[]) to match everything instead"
        )
    return Or(children=[Term(term=t) for t in terms])


def _is_group(item: object) -> bool:
    return isinstance(item, (list, tuple))


def build_mandatories_expr(
    mandatories: Union[Sequence[str], Sequence[Sequence[str]]],
) -> BooleanExpr:
    """`mandatories` per §2, covering both shapes:

    - Flat list of terms -> a single AND group:
      `[term1, term2, term3]` -> `term1 AND term2 AND term3`
    - List of term-groups -> OR across ANDed groups (grouped-mandatories):
      `[[A1,A2,A3], [B1,B2,B3]]` -> `(A1∧A2∧A3) OR (B1∧B2∧B3)`

    The flat case is not a special case of this function's logic -- it's
    exactly the grouped case with one group, minus the (unnecessary)
    outer `Or` wrapper. Both shapes go through the same "build one `And`
    per group" step; only whether to wrap the result in `Or` differs.

    Raises if `mandatories` (or any group within it) is empty, or if the
    list mixes bare terms with term-groups (e.g. `["a", ["b", "c"]]`) --
    that shape is ambiguous and should fail loudly rather than guess
    which reading was intended.
    """
    groups = list(mandatories)
    if not groups:
        raise ValueError(
            "mandatories must contain at least one term or group; omit "
            "the rule entirely (or pass None/[]) to match everything instead"
        )

    is_group_flags = [_is_group(item) for item in groups]
    if any(is_group_flags) and not all(is_group_flags):
        raise ValueError(
            "mandatories must not mix bare terms with term-groups "
            "(e.g. ['a', ['b', 'c']]) -- use either a flat list of terms "
            "or a list of term-group lists, not both"
        )

    if all(is_group_flags):
        and_nodes: List[BooleanExpr] = []
        for group in groups:
            group_terms = list(group)  # type: ignore[arg-type]
            if not group_terms:
                raise ValueError("each mandatories group must contain at least one term")
            and_nodes.append(And(children=[Term(term=t) for t in group_terms]))
        return Or(children=and_nodes)

    # Flat case: a single implicit AND group, no outer Or needed.
    return And(children=[Term(term=t) for t in groups])  # type: ignore[arg-type]


class LexicalQuery(BaseModel):
    """The `first_of` / `mandatories` rule as a use-case config (or a
    request) declares it, before it's compiled into a `BooleanExpr`.

    Both fields are optional and independently default to "no
    constraint" -- see `to_boolean_expr()`. When both are given, the
    overall match requires `mandatories` AND at least one of `first_of`
    (the same "must" + "should" combination familiar from other boolean
    search systems): `first_of` alone can't be satisfied by a document
    that fails a mandatory requirement, and vice versa.
    """

    model_config = ConfigDict(extra="forbid")

    first_of: Optional[List[str]] = None
    mandatories: Optional[Union[List[str], List[List[str]]]] = None

    @field_validator("first_of")
    @classmethod
    def first_of_terms_not_blank(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for term in v:
                if not term or not term.strip():
                    raise ValueError("first_of terms must not be blank")
        return v

    @model_validator(mode="after")
    def mandatories_terms_not_blank(self) -> "LexicalQuery":
        if self.mandatories is not None:
            for item in self.mandatories:
                terms = item if isinstance(item, list) else [item]
                for term in terms:
                    if not term or not term.strip():
                        raise ValueError("mandatories terms must not be blank")
        return self

    def to_boolean_expr(self) -> BooleanExpr:
        """Compile this rule into a `BooleanExpr` tree.

        An empty list is treated the same as `None` (both mean "this
        part of the rule wasn't specified") -- so a query with
        `first_of=[]` and `mandatories=None`, or with both fields simply
        omitted, both resolve to `MatchAll()` rather than either raising
        or matching nothing. This is what satisfies the "empty/undefined
        rule must default to match all, not error" requirement.
        """
        parts: List[BooleanExpr] = []
        if self.first_of:
            parts.append(build_first_of_expr(self.first_of))
        if self.mandatories:
            parts.append(build_mandatories_expr(self.mandatories))

        if not parts:
            return MatchAll()
        if len(parts) == 1:
            return parts[0]
        return And(children=parts)
