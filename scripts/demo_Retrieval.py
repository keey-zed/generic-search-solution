#!/usr/bin/env python3
"""
scripts/demo_Retrieval.py

Run this from the repo root to SEE Retrieval's Definition of Done in
action on the terminal: a fixed fake corpus + fake embeddings, run
through semantic-only, lexical-only, and combined (ranked + paginated)
queries, with every intermediate result printed.

    PYTHONPATH=. python3 scripts/demo_Retrieval.py

This is a demo/inspection script, not a test -- see
tests/test_Retrieval_definition_of_done.py for the assertions that pin
these exact numbers down as a regression test.
"""
from __future__ import annotations

from app.core.search.lexical.engine import lexical_search
from app.core.search.lexical.query import LexicalQuery
from app.core.search.pagination.engine import paginate
from app.core.search.ranking.engine import merge_and_rank
from app.core.search.semantic.engine import SemanticQuery, semantic_search
from app.core.search.semantic.vector_store import InMemoryVectorStore

# ---------------------------------------------------------------------------
# The fixed fake corpus + fixed fake embeddings.
# ---------------------------------------------------------------------------

TEXT_CORPUS = [
    ("item-1", "red circle spinning"),
    ("item-2", "blue circle bouncing"),
    ("item-3", "red square resting"),
    ("item-4", "green triangle rolling"),
    ("item-5", "blue triangle flying"),
]

EMBEDDINGS = {
    "item-1": [1.0, 0.0],
    "item-2": [0.8, 0.6],
    "item-3": [0.6, 0.8],
    "item-4": [0.0, 1.0],
    "item-5": [-1.0, 0.0],
}

QUERY_VECTOR = [1.0, 0.0]

TEXT_BY_ID = dict(TEXT_CORPUS)


def fixed_vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore(list(EMBEDDINGS.items()))


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    section("FIXED FAKE CORPUS (id -> text)")
    for doc_id, text in TEXT_CORPUS:
        print(f"  {doc_id:8s} -> \"{text}\"")

    section("FIXED FAKE EMBEDDINGS (id -> 2D vector)")
    for doc_id, vector in EMBEDDINGS.items():
        print(f"  {doc_id:8s} -> {vector}")
    print(f"\n  Query vector: {QUERY_VECTOR}  (same direction as item-1)")

    # -----------------------------------------------------------------
    # 1) Semantic-only query
    # -----------------------------------------------------------------
    section("1) SEMANTIC-ONLY QUERY")
    semantic_hits = semantic_search(
        fixed_vector_store(), [SemanticQuery(vector=QUERY_VECTOR)], top_k=5
    )
    print(f"semantic_search(query_vector={QUERY_VECTOR}, top_k=5) ->\n")
    for hit in semantic_hits:
        print(f"  id={hit.id:8s}  score={hit.score:+.4f}  matched_fields={hit.matched_fields}")

    # -----------------------------------------------------------------
    # 2) Lexical-only queries
    # -----------------------------------------------------------------
    section("2) LEXICAL-ONLY QUERIES")

    print("\n-- first_of=['red', 'blue']  (OR)")
    or_hits = lexical_search(TEXT_CORPUS, LexicalQuery(first_of=["red", "blue"]))
    for hit in or_hits:
        print(f"  id={hit.id:8s}  score={hit.score}  text=\"{TEXT_BY_ID[hit.id]}\"")
    print("  (item-4 'green triangle rolling' excluded: no 'red' or 'blue')")

    print("\n-- mandatories=['circle']  (AND, single group)")
    and_hits = lexical_search(TEXT_CORPUS, LexicalQuery(mandatories=["circle"]))
    for hit in and_hits:
        print(f"  id={hit.id:8s}  score={hit.score}  text=\"{TEXT_BY_ID[hit.id]}\"")

    print("\n-- mandatories=[['red','circle'], ['blue','triangle']]  (grouped AND/OR)")
    grouped_hits = lexical_search(
        TEXT_CORPUS, LexicalQuery(mandatories=[["red", "circle"], ["blue", "triangle"]])
    )
    for hit in grouped_hits:
        print(f"  id={hit.id:8s}  score={hit.score}  text=\"{TEXT_BY_ID[hit.id]}\"")
    print("  (item-1 satisfies group 1 'red AND circle'; item-5 satisfies group 2 'blue AND triangle')")

    print("\n-- LexicalQuery() with nothing set  (undefined rule -> match all)")
    all_hits = lexical_search(TEXT_CORPUS, LexicalQuery())
    print(f"  matched ids: {[h.id for h in all_hits]}")

    # -----------------------------------------------------------------
    # 3) Combined query: semantic + lexical -> merge_and_rank -> paginate
    # -----------------------------------------------------------------
    section("3) COMBINED QUERY: semantic + lexical('red'/'blue') -> merge_and_rank -> paginate")

    lexical_hits = lexical_search(TEXT_CORPUS, LexicalQuery(first_of=["red", "blue"]))
    print("Semantic hits:", [(h.id, h.score) for h in semantic_hits])
    print("Lexical hits: ", [h.id for h in lexical_hits])

    ranked = merge_and_rank(semantic_hits, lexical_hits)
    lexical_ids = {h.id for h in lexical_hits}
    semantic_scores = {h.id: h.score for h in semantic_hits}

    print("\nmerge_and_rank() with default weights {semantic: 0.5, lexical: 0.5}:\n")
    print(f"  {'id':10s}{'semantic':>10s}{'lexical?':>10s}{'combined':>10s}")
    for hit in ranked:
        print(
            f"  {hit.id:10s}"
            f"{semantic_scores.get(hit.id, 0.0):>10.2f}"
            f"{'yes' if hit.id in lexical_ids else 'no':>10s}"
            f"{hit.score:>10.2f}"
        )

    print("\npaginate(ranked, page=1, page_size=2):")
    page_1 = paginate(ranked, page=1, page_size=2)
    print(
        f"  hits={[h.id for h in page_1.hits]}  "
        f"total_hits={page_1.total_hits}  total_pages={page_1.total_pages}  "
        f"has_next={page_1.has_next}"
    )

    print("\npaginate(ranked, page=3, page_size=2):")
    page_3 = paginate(ranked, page=3, page_size=2)
    print(
        f"  hits={[h.id for h in page_3.hits]}  "
        f"has_previous={page_3.has_previous}  has_next={page_3.has_next}"
    )
    print()


if __name__ == "__main__":
    main()
