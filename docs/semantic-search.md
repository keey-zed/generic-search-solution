# Semantic Search Module

Single- and multi-query embedding similarity search, living under
`app/core/search/semantic/`.

Run tests from the repo root with `app/` importable, same as the rest of
the project:

```bash
PYTHONPATH=. python3 -m pytest tests/test_semantic_search.py
```

## 1. Pipeline

```
SemanticQuery(ies)
      |
      v
VectorStore.search()  — one call per query
      |
      v
combination strategy (by name) — merges per-query results into one
      |            {document_id: combined_score}
      v
sort desc by score, tie-break by id, truncate to top_k
      |
      v
List[SearchHit]
```

## 2. Files

| File | Role |
|---|---|
| `vector_store.py` | The `VectorStore` protocol, the `VectorMatch` result shape, `cosine_similarity`, and `InMemoryVectorStore` — the fake/in-memory store used by tests (and usable as-is for small corpora). |
| `combination.py` | The multi-query combination strategy registry: `max_score` and `weighted_average`, selectable by name. |
| `engine.py` | `SemanticQuery` (the request shape) and `semantic_search()`, the public entry point. |

## 3. `VectorStore` — the interface, not an implementation

Mirrors the pattern already used by `EmbeddingProvider`
(`app/core/embeddings/provider.py`), and is a **different concern** from
it:

| | Question it answers |
|---|---|
| `EmbeddingProvider` | "What is *this document's own* embedding?" (lookup by id) |
| `VectorStore` | "Which document ids are closest to *this query* vector?" (similarity search) |

```python
class VectorStore(Protocol):
    def search(self, query_vector: Sequence[float], top_k: int) -> List[VectorMatch]: ...
```

Semantic retrieval code must only ever call `VectorStore.search()`. It
never assumes FAISS, a hosted vector DB, or an in-memory dict — swapping
in a real backend later means writing one new class satisfying this
protocol, with zero changes to `engine.py`.

`InMemoryVectorStore` is the only implementation today: brute-force
cosine similarity, pure Python (no numpy/faiss), so unit tests for this
module never depend on infra. Ties are broken by id, ascending, so
results are deterministic.

## 4. Multi-query combination — configurable, not hardcoded

The source doc (§2) and `SemanticSearchConfig.multi_query_combination`
(`app/core/config/models.py`) already fix two strategy names for v0:

- **`max_score`** (default) — for each document, keep the highest score
  it received across any query. Right for "alternative phrasings of the
  same intent" — a document should rank highly if it matches strongly on
  *any one* phrasing.
- **`weighted_average`** — for each document, the weighted mean of its
  score across all queries, using each `SemanticQuery.weight` (default
  `1.0`, i.e. equal weighting). A document missing from one query's
  candidate set contributes `0.0` for that query rather than being
  excluded. Right for "queries expressing different facets that should
  all contribute."

Both are registered under `combination.py`'s `@register_strategy`
decorator against a shared signature:

```python
(per_query_matches: Sequence[List[VectorMatch]], weights: Sequence[float]) -> Dict[str, float]
```

`weights` is always passed, even to strategies (like `max_score`) that
ignore it — a uniform signature is what lets `engine.py` (and, later,
the YAML config loader) select a strategy by name with no
strategy-specific branch. Adding a third strategy is "register a new
function here," never a change to `engine.py`.

## 5. `semantic_search()` — single query is not a special case

```python
def semantic_search(
    vector_store: VectorStore,
    queries: Sequence[SemanticQuery],
    *,
    top_k: int,
    strategy: str = "max_score",
    candidate_pool_size: Optional[int] = None,
) -> List[SearchHit]: ...
```

A single-query search is simply `queries=[one SemanticQuery]` — there is
no separate single-query code path, because every combination strategy
is a no-op when there is only one query's results to merge.

- `candidate_pool_size` (default: `top_k`) controls how many candidates
  are pulled from `vector_store` **per query** before combining. Raise it
  if a document that's strong on one query but merely adequate on others
  is being pushed out before combination ever sees it.
- Output is `List[SearchHit]` (`app/core/schema/search_hit.py`) with
  `matched_fields=["text"]` and `metadata={}` — enriching a hit with its
  document's metadata is the API layer's job, not retrieval's.
- Results are sorted by combined score descending, tie-broken by id
  ascending, so results are deterministic across repeated calls with the
  same inputs.

## 6. What's deliberately NOT built here

- **No text → vector embedding step.** `semantic_search()` only accepts
  already-computed query vectors (`SemanticQuery.vector`). Turning user
  query text into a vector is a concern for something upstream of this
  module (an embedding model, or a future `QueryEmbedder`-style
  interface) — exactly as `EmbeddingProvider` stays out of "how documents
  got embedded."
- **No FAISS/vector-DB-backed `VectorStore`.** Add one only when a real
  project needs it at scale; the protocol exists precisely so that's a
  new class, not a rewrite of this module.
- **No use-case field names or domain vocabulary anywhere in this
  module** — it only knows ids, vectors, and scores, per the roadmap's
  ground rule that the generic core never imports use-case knowledge.
