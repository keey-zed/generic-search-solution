# Ranking & Merging

Merging semantic and lexical result sets into one ranked list via a
pluggable ranking strategy, living under `app/core/search/ranking/`.

Run tests from the repo root with `app/` importable, same as the rest of
the project:

```bash
PYTHONPATH=. python3 -m pytest tests/test_ranking.py
```

## 1. Files

| File | Role |
|---|---|
| `strategies.py` | `SourceSignal` (the per-document input every strategy receives), the strategy registry (`register_strategy`/`get_strategy`/`available_strategies`), and the one required implementation, `weighted_sum`. |
| `engine.py` | `merge_and_rank()`, the public entry point that turns two `List[SearchHit]`s into one. |

## 2. Pipeline

```
semantic_hits, lexical_hits (List[SearchHit] each)
      |
      v
per-id SourceSignal: which source(s) hit this id, and how
      |
      v
named ranking strategy (registry, e.g. "weighted_sum") -> {id: combined_score}
      |
      v
sort desc by score, tie-break by id
      |
      v
List[SearchHit] -- score replaced by combined score;
                   matched_fields / snippet / metadata reconciled
```

A document is included if **either** source returned it — this is a
union, not an intersection, and each input may be empty (e.g. a project
with `search.lexical.enabled: false` never produces lexical hits at
all; ranking degrades gracefully to semantic-only).

## 3. The pluggability seam

The roadmap's requirement here is explicit: "interface only needs one
real implementation now, e.g. weighted sum — but the seam must exist."
This mirrors `app/core/search/semantic/combination.py`'s registry
pattern on purpose, for the same reason:

```python
RankingStrategy = Callable[[Mapping[str, SourceSignal], Mapping[str, float]], Dict[str, float]]
```

`engine.py::merge_and_rank()` selects a strategy by name
(`get_strategy(strategy)`) — it never branches on strategy identity
itself. `app/core/config/models.py`'s `RankingConfig.strategy` is
already typed `Literal["weighted_sum"]` for v0; widening that Literal
and adding one `@register_strategy("...")`-decorated function in
`strategies.py` is the entire cost of a second strategy (e.g. reciprocal
rank fusion) — `engine.py` and every call site stay unchanged. A test in
`test_ranking.py`
(`test_seam_supports_a_second_strategy_with_no_engine_changes`)
registers a throwaway strategy at runtime and calls it by name through
`merge_and_rank()` to demonstrate exactly this.

## 4. `weighted_sum`

```
score = weights["semantic"] * semantic_score + weights["lexical"] * lexical_indicator
```

- `semantic_score` is the document's `SearchHit.score` from semantic
  retrieval, or `0.0` if it wasn't a semantic hit at all.
- `lexical_indicator` is `1.0` if the document was among the lexical
  hits, `0.0` otherwise — lexical retrieval is boolean
  (`SearchHit.score is None`, see `app/core/search/lexical/engine.py`),
  so it can only contribute a present/absent signal, never a continuous
  one.
- `weights` defaults to `{"semantic": 0.5, "lexical": 0.5}`
  (`DEFAULT_WEIGHTS` in `engine.py`), matching `RankingWeights`'s own
  defaults in the config schema. Pass a project's actual
  `search.ranking.weights` values through instead once the config layer
  is wired up.
- Raises if every weight is non-positive, mirroring
  `RankingConfig.weights_not_both_zero`'s reasoning — a ranking that can
  never score anything above zero is a config error, not a valid (if
  useless) ranking.

**Known scope boundary — no score renormalization.** `weighted_sum`
assumes `semantic_score` is already in a range where summing it against
a `[0, 1]` lexical indicator is meaningful (e.g. cosine similarity, or a
project-specific normalization applied upstream). This module doesn't
renormalize scores itself. That's a deliberate simplification, not an
oversight: score normalization is a judgment call (min-max? clip
negatives? something use-case-specific?) with no single generically
"correct" answer, so — following this project's own "start
use-case-specific, promote to generic once it proves reusable"
principle (source doc §4) — it's left as a place a project can layer
its own normalization before calling `merge_and_rank`, or a future
strategy can bake in, rather than guessed at here.

## 5. Field reconciliation

Beyond score, `merge_and_rank` reconciles the rest of `SearchHit` across
the two sources for whichever ids survive:

| Field | Rule |
|---|---|
| `matched_fields` | Union, deduplicated, first-seen order preserved. |
| `snippet` | Whichever source has one; semantic's wins if both do (arbitrary but deterministic — there's no principled reason to prefer one over the other in general). |
| `metadata` | Union of both sources' dicts; semantic's value wins on a key present in both. |

In practice, both `semantic_search()` and `lexical_search()` currently
return `metadata={}` and `snippet=None` (attaching a document's actual
metadata to a hit is the API layer's job, not retrieval's — see
their own docstrings), so these rules rarely activate today. They exist
so `merge_and_rank` has well-defined, tested behavior once a retrieval
source does start attaching them, rather than leaving it as a surprise
to work out later.

## 6. What's deliberately NOT built here

- **No score renormalization** — see §4's "Known scope boundary."
- **No dependency on `app.core.config`.** `weights` is a plain
  `Mapping[str, float]`, not `RankingWeights`, so this module is
  testable and usable without constructing a full use-case config; the
  API layer is expected to pass `config.search.ranking.weights.model_dump()`
  (or equivalent) through when it wires this up.
- **No pagination.** `merge_and_rank` returns the full ranked list;
  slicing it into pages is `PaginationConfig`'s concern (see
  `SearchHit`'s own module docstring on the retrieval → ranking →
  pagination split), not this module's.
