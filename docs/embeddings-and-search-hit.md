# Embeddings Interface & Generic SearchHit Schema

Building directly on `DocumentRecord` and the typed metadata
layer described in `docs/metadata-typing.md` — read that first if you
haven't.

Run tests from the repo root with `app/` importable, same as the rest of
the project:

```bash
PYTHONPATH=. python3 -m pytest tests/
```

## 1. Embeddings: interface vs. V1 storage

**The problem this avoids:** if retrieval code reads a vector straight
off a record (`record.embedding`), every retrieval function is now
coupled to "embeddings live inline on a document." Moving to a separate
embeddings table or a vector DB later means rewriting retrieval, not
just swapping a storage class.

**The fix — one interface, one V1 implementation:**

```
Retrieval → EmbeddingProvider → InlineEmbeddingProvider → EmbeddedDocumentRecord   (built now)
                              → a separate embeddings store / vector DB            (not built — future)
```

| Piece | File | Role |
|---|---|---|
| `Embedding` | `app/core/schema/embedding.py` | The vector + provenance shape itself. |
| `EmbeddedDocumentRecord` | `app/core/schema/embedding.py` | V1 storage shape: a `DocumentRecord` plus an optional `embedding`. |
| `EmbeddingProvider` | `app/core/embeddings/provider.py` | The interface retrieval is allowed to depend on. `Protocol`, not a base class — any object with a matching `get_embedding` method satisfies it, no inheritance required. |
| `InlineEmbeddingProvider` | `app/core/embeddings/provider.py` | The only implementation that exists today. Reads embeddings straight from a list of `EmbeddedDocumentRecord` held in memory. |

Retrieval code should only ever call `provider.get_embedding(document_id)`.
It must never import `EmbeddedDocumentRecord` or reach into any
provider's internals — that's the line that keeps a future swap to a
vector DB from touching retrieval code at all.

### Why `Embedding` isn't just `list[float]`

```python
class Embedding(BaseModel):
    vector: list[float]
    model_id: str          # required
    # dim is NOT a stored field — it's `len(vector)`, always in sync
```

- `model_id` is required because vectors from two different embedding
  models (or two versions of one model) aren't comparable — averaging or
  comparing them silently produces garbage similarity scores with no
  visible error. Every `Embedding` carries the tag needed to catch that.
- `dim` is a computed property (`len(vector)`), not a separate stored
  field, specifically so it can never drift out of sync with the actual
  vector.
- The vector is validated to reject `NaN`/`Inf` values at construction
  time.

### Why `embedding` lives on a separate model, not on `DocumentRecord`

`DocumentRecord` (`app/core/schema/document.py`) is explicitly documented
as "text + metadata only," with `extra="forbid"` — so a stray `embedding`
key on a raw `DocumentRecord` fails validation loudly (there's a test for
this: `test_unknown_top_level_field_rejected` in
`tests/test_document_schema.py`, and its embedding-specific counterpart
in `tests/test_embeddings.py`). Bolting `embedding` onto `DocumentRecord`
itself would mean every project's wire format changes shape depending on
whether it happens to use inline embeddings — exactly the kind of
storage-choice leakage this deliverable exists to prevent.

`EmbeddedDocumentRecord(DocumentRecord)` adds `embedding: Optional[Embedding] = None`
as a genuinely new field on a subclass, not an extra key — so:

- **Optionality**: a document without an embedding yet (new upload,
  embedding job hasn't run, deliberately text-only) is just
  `embedding=None`. `None` is a normal, expected state, not an error.
- **Backwards compatibility**: any dict/record shaped like the
  pre-embedding `DocumentRecord` still validates as an
  `EmbeddedDocumentRecord` unchanged — `embedding` simply comes out
  `None`. No migration step is needed to adopt this model.

### Consistency check in `InlineEmbeddingProvider`

At construction, `InlineEmbeddingProvider` checks that every non-`None`
embedding it was given shares the same `model_id`, and raises immediately
if not. A provider silently serving vectors from two different models
would make any similarity search over it meaningless with no visible
symptom — better to fail loudly when the provider is built than deep
inside a later ranking computation. It also exposes
`get_embedding_dimension()` so retrieval can validate a query vector's
shape before using it, for the same fail-fast reason.

### What's deliberately NOT built yet

- No vector-DB or dedicated-embeddings-table implementation of
  `EmbeddingProvider`. Add one only when a real project needs it — the
  interface exists precisely so that's a new class, not a retrieval
  rewrite.
- No batch/bulk `get_embeddings(ids)` method on the interface. Add it if
  and when a real retrieval path needs to avoid N single lookups; v0's
  `InlineEmbeddingProvider` is an in-memory dict either way, so there's
  no performance case for it yet.

## 2. `SearchHit` — the generic retrieval result

### Where it sits in the pipeline

```
Documents
   ↓
Retrieval        — decides WHICH documents match, produces one SearchHit per match
   ↓
List[SearchHit]
   ↓
Ranking          — decides ORDER (may use/recompute `score`); doesn't change hit contents
   ↓
Pagination       — decides which SLICE of the ordered list a given request sees
   ↓
API
```

This is why `SearchHit` intentionally has **no** rank/position, page
number, or offset on it — those describe a *request* or a *list*, not an
individual result. If a future need arises to expose a hit's position in
a result set, that belongs on a page/response wrapper model, not on
`SearchHit` (and `SearchHit.model_config = ConfigDict(extra="forbid")`
means adding a stray `rank`/`page` field fails validation loudly instead
of quietly working).

### Shape

```python
class SearchHit(BaseModel):
    id: str
    score: float | None = None
    matched_fields: list[str] = []
    snippet: Snippet | None = None
    metadata: dict[str, TypedMetadataValue] = {}

class Snippet(BaseModel):
    text: str
    highlight_ranges: list[tuple[int, int]] = []
```

| Field | Why it's typed this way |
|---|---|
| `id` | Matches the source `DocumentRecord.id` — every hit refers back to exactly one record. |
| `score` | `Optional[float]`, not `float`. Not every retrieval strategy produces one — boolean/substring lexical matching or a pure metadata filter has no ranking signal at all. `None` means "not applicable," never a stand-in for zero relevance. Validated to reject `NaN`/`Inf`. |
| `matched_fields` | Generic strings drawn from a project's own field vocabulary: `"text"` for the main content field, or a metadata key like `"author"`, `"doctype"`, `"genre"`. **Never** a domain-specific name like `matched_legal_type` — that knowledge belongs in a UI's per-project label mapping, not in the schema. |
| `snippet` | Reuses the (matched text + character ranges) idea already used by the legacy lexical/semantic code in `app/routes.py` (`_sanitize_source_ranges`, `_build_item`'s `chunk`/`source_ranges` pair), generalized into a validated model and renamed away from the legal-corpus-specific "chunk." Optional because a metadata-only match may have nothing to highlight. `highlight_ranges` are validated as in-bounds, non-negative, and `end > start`. |
| `metadata` | Reuses `metadata_types.TypedMetadataValue` — the exact same typed shape every `NormalizedDocument.metadata` already carries (see `docs/metadata-typing.md` §3). `SearchHit` does not invent a second metadata representation. |

### Example

```python
from app.core.schema.search_hit import SearchHit, Snippet

hit = SearchHit(
    id="doc-142",
    score=0.87,
    matched_fields=["text", "doctype"],
    snippet=Snippet(text="...promulgated by dahir on...", highlight_ranges=[(15, 20)]),
    metadata={"doctype": "dahir", "lawnumber": "1-18-XX"},
)
```

The same shape works unchanged for a books use case:

```python
hit = SearchHit(
    id="book-9",
    score=None,                       # e.g. plain substring match, no ranking signal
    matched_fields=["author"],
    metadata={"author": "Camus", "genre": ["fiction"]},
)
```

Nothing about `SearchHit` changes between these two — that's the point.