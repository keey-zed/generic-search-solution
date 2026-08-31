# Retrieval — Definition of Done

> Given a fixed fake corpus + fake embeddings, semantic, lexical, and
> combined queries return deterministic, tested results. No use-case
> field names appear anywhere in this code.

This is verified by two test files, both under `tests/`:

## 1. `test_Retrieval_definition_of_done.py` — deterministic, tested results

One fixed corpus (`_FIXED_TEXT_CORPUS`, 5 documents of neutral
color/shape text) and one fixed set of embeddings (`_FIXED_EMBEDDINGS`,
hand-picked 2D vectors) are defined once at module level. Every test
below runs against that same fixed data:

| Query type | What's checked |
|---|---|
| Semantic-only | `semantic_search()` against the fixed embeddings returns the exact expected `(id, score)` pairs — cosine similarities verified by hand in the code comments — not just "looks plausibly ordered." |
| Lexical-only | `lexical_search()` covers `first_of`, `mandatories`, grouped `mandatories`, and the undefined-rule-matches-all case, each against exact expected id lists. |
| Combined | `semantic_search()` → `lexical_search()` → `merge_and_rank()` → `paginate()`, with the exact `weighted_sum` scores worked out by hand (including a genuine score tie, resolved by the documented id tie-break) and exact page contents. |

Every one of the three query types also has an explicit
"run it twice, assert identical output" test, since determinism is the
property actually being asserted, not just correctness of a single run.

## 2. `test_no_domain_vocabulary.py` — no use-case field names

Rather than a one-time manual audit, this is a permanent test that
scans every `.py` file under `app/core/search/` for a blocklist of
terms, and fails (naming the offending file and term) if any appear.
The blocklist is drawn directly from the source material, not guessed:

- The architecture doc's own §9 example metadata fields for its two
  running example domains (legal search: `promulgation_date`,
  `publication_date`, `document_type`, `issuing_authority`,
  `cross_references`, `jurisdiction`; book search: `author`, `volume`,
  `chapter`, `source_collection`).
- The roadmap's own §11 named example/future applications ("Legal
  Search," "Justice Search," "Bulletin Officiel Search," "Book Search,"
  "Administrative Document Search," "Public Employment Search").

This means any future change to `semantic/`, `lexical/`, `ranking/`, or
`pagination/` that accidentally leaks a domain concept in a variable
name, a docstring, or a config key gets caught immediately in CI, not
in review.

## Running both

```bash
PYTHONPATH=. python3 -m pytest tests/test_Retrieval_definition_of_done.py tests/test_no_domain_vocabulary.py -v
```

At the time of writing, the full test suite is **334 passing tests, 0 failures**:

```bash
PYTHONPATH=. python3 -m pytest tests/ -q
```
