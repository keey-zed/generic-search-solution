# Lexical/Boolean Search Module

`first_of`/`mandatories` boolean lexical matching, living under
`app/core/search/lexical/`.

Run tests from the repo root with `app/` importable, same as the rest of
the project:

```bash
PYTHONPATH=. python3 -m pytest tests/test_lexical_search.py
```

## 1. Files

| File | Role |
|---|---|
| `boolean_expr.py` | The generic boolean-expression tree: `BooleanExpr` base, `Term`, `And`, `Or`, `MatchAll`, each implementing one `evaluate(predicate)` method. |
| `query.py` | `LexicalQuery` (the `first_of`/`mandatories` request shape) and the builder functions that compile it into a `BooleanExpr`. |
| `engine.py` | `contains_predicate` (the default substring `TermPredicate`) and `lexical_search()`, the public entry point. |

## 2. Why a tree, not a two-level loop

The roadmap is explicit: implement the grouped-mandatories case "as a
generic boolean-expression evaluator, not a special-cased two-level
loop, so a future NOT or deeper nesting doesn't require a rewrite."

`boolean_expr.py` has exactly one contract new node types must satisfy —
`evaluate(predicate) -> bool` — so:

- **Grouped mandatories is not a dedicated node.** `mandatories = [[A1,A2,A3],[B1,B2,B3]]`
  compiles to `Or(children=[And(children=[Term(A1),Term(A2),Term(A3)]), And(children=[Term(B1),Term(B2),Term(B3)])])`
  — the exact same `Or`/`And` classes `first_of` and flat `mandatories`
  already use, just composed one level deeper.
- **Deeper nesting already works.** Because `And.children` and
  `Or.children` are typed as `BooleanExpr` (the base class), not `Term`,
  arbitrarily deep trees evaluate correctly today with zero extra code —
  see `test_deeper_nesting_works_with_no_special_casing` in the test
  file.
- **Adding NOT later is one new class:**

  ```python
  class Not(BooleanExpr):
      child: BooleanExpr
      def evaluate(self, predicate):
          return not self.child.evaluate(predicate)
  ```

  No existing node type, `query.py`'s builders, or `engine.py`'s
  `lexical_search()` needs to change.

## 3. `first_of` / `mandatories` → `BooleanExpr`

| Config shape | Compiles to |
|---|---|
| `first_of = [t1, t2, t3]` | `Or(Term(t1), Term(t2), Term(t3))` |
| `mandatories = [t1, t2, t3]` | `And(Term(t1), Term(t2), Term(t3))` |
| `mandatories = [[A1,A2,A3],[B1,B2,B3]]` | `Or(And(A1,A2,A3), And(B1,B2,B3))` |
| neither given (or both empty) | `MatchAll()` |
| both `first_of` and `mandatories` given | `And(first_of_expr, mandatories_expr)` — must satisfy the mandatory group(s) **and** at least one `first_of` term, the familiar "must + should" combination |

`build_mandatories_expr()` detects the flat-vs-grouped shape by
inspecting whether its items are themselves lists; a list mixing bare
terms with term-groups (e.g. `["a", ["b", "c"]]`) raises rather than
guessing which reading was intended — `LexicalQuery`'s
`Optional[Union[List[str], List[List[str]]]]` typing already rejects
this shape at the Pydantic layer for config-driven use, and the builder
function re-checks defensively for callers that build a rule
programmatically instead of through `LexicalQuery`.

## 4. Empty/undefined rule → match all, not an error

A lexical query with no `first_of` and no `mandatories` (fields omitted, or explicitly `[]`) must match every candidate. `LexicalQuery.to_boolean_expr()` treats `None` and `[]` identically (both mean "this part of the rule wasn't specified") and returns `MatchAll()` when neither field contributes anything — never a `ValueError`, and never "matches nothing."

## 5. `lexical_search()` and the default predicate

```python
def lexical_search(
    documents: Iterable[Tuple[str, str]],
    rule: LexicalQuery,
    *,
    case_sensitive: bool = False,
) -> List[SearchHit]: ...
```

- `documents` is a plain iterable of `(id, text)` pairs — narrowing the
  candidate set (e.g. to documents that already passed metadata filters)
  is the caller's job, not this function's.
- Matching uses `contains_predicate`: plain substring containment,
  **case-insensitive by default** (documented here as this module's
  default, per the roadmap's note that a contains-style match needs "a
  documented case-sensitivity default"). Pass `case_sensitive=True`, or
  call `expr.evaluate()` directly with a different `TermPredicate`
  (exact match, fuzzy match, …), for anything else.
- Every returned `SearchHit.score` is `None` — boolean matching has no
  inherent relevance signal, exactly the "not applicable" case
  `SearchHit.score`'s own docstring describes.
- Results are sorted by `id` ascending, so output is deterministic
  regardless of `documents`' iteration order.

## 6. What's deliberately NOT built here

- **No tokenization, stemming, or normalization** (e.g. the
  Arabic-diacritics handling in the legacy `app/semantic_engine.py`).
  `contains_predicate` is intentionally the simplest possible default;
  a project needing normalization supplies its own `TermPredicate`.
- **No corpus/index abstraction.** `lexical_search()` takes a plain
  iterable, mirroring how narrow a job this module has: evaluate a
  boolean rule against text. Building an actual searchable index over a
  large corpus is out of scope for this deliverable.
- **No `NOT` node.** Not requested by the current config schema
  (`first_of`/`mandatories` only) — see §2 for why adding one later
  doesn't require touching this module's existing code.
