import pytest
from pydantic import ValidationError

from app.core.schema.search_hit import SearchHit
from app.core.search.lexical.engine import lexical_search
from app.core.search.lexical.query import LexicalQuery
from app.core.search.pagination.engine import SearchResultPage, paginate
from app.core.search.ranking.engine import merge_and_rank
from app.core.search.semantic.engine import SemanticQuery, semantic_search
from app.core.search.semantic.vector_store import InMemoryVectorStore


def _hits(n):
    return [SearchHit(id=f"doc-{i}", score=float(n - i)) for i in range(n)]


# ---------------------------------------------------------------------------
# Basic slicing
# ---------------------------------------------------------------------------


def test_paginate_first_page():
    page = paginate(_hits(25), page=1, page_size=10)
    assert [h.id for h in page.hits] == [f"doc-{i}" for i in range(10)]
    assert page.page == 1
    assert page.page_size == 10
    assert page.total_hits == 25
    assert page.total_pages == 3
    assert page.has_previous is False
    assert page.has_next is True


def test_paginate_middle_page():
    page = paginate(_hits(25), page=2, page_size=10)
    assert [h.id for h in page.hits] == [f"doc-{i}" for i in range(10, 20)]
    assert page.has_previous is True
    assert page.has_next is True


def test_paginate_last_page_partial():
    page = paginate(_hits(25), page=3, page_size=10)
    assert [h.id for h in page.hits] == [f"doc-{i}" for i in range(20, 25)]
    assert len(page.hits) == 5
    assert page.has_previous is True
    assert page.has_next is False


def test_paginate_does_not_reorder_hits():
    hits = [SearchHit(id="z", score=0.1), SearchHit(id="a", score=99.0)]
    page = paginate(hits, page=1, page_size=10)
    # Input order preserved even though "a" has a much higher score --
    # paginate trusts the caller already ranked this.
    assert [h.id for h in page.hits] == ["z", "a"]


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------


def test_paginate_page_beyond_range_returns_empty_not_error():
    page = paginate(_hits(25), page=50, page_size=10)
    assert page.hits == []
    assert page.has_next is False
    assert page.total_pages == 3


def test_paginate_empty_result_set():
    page = paginate([], page=1, page_size=10)
    assert page.hits == []
    assert page.total_hits == 0
    assert page.total_pages == 0
    assert page.has_previous is False
    assert page.has_next is False


def test_paginate_exact_multiple_of_page_size_has_no_trailing_empty_page():
    page = paginate(_hits(20), page=2, page_size=10)
    assert len(page.hits) == 10
    assert page.total_pages == 2
    assert page.has_next is False


# ---------------------------------------------------------------------------
# page_size resolution
# ---------------------------------------------------------------------------


def test_paginate_uses_default_page_size_when_omitted():
    page = paginate(_hits(50), page=1, default_page_size=15)
    assert page.page_size == 15
    assert len(page.hits) == 15


def test_paginate_clamps_page_size_above_max_instead_of_erroring():
    page = paginate(_hits(200), page=1, page_size=500, max_page_size=100)
    assert page.page_size == 100
    assert len(page.hits) == 100


def test_paginate_page_size_under_max_is_unaffected():
    page = paginate(_hits(200), page=1, page_size=30, max_page_size=100)
    assert page.page_size == 30


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


def test_paginate_rejects_page_zero():
    with pytest.raises(ValueError):
        paginate(_hits(10), page=0, page_size=5)


def test_paginate_rejects_negative_page():
    with pytest.raises(ValueError):
        paginate(_hits(10), page=-1, page_size=5)


def test_paginate_rejects_zero_page_size():
    with pytest.raises(ValueError):
        paginate(_hits(10), page=1, page_size=0)


def test_paginate_rejects_negative_page_size():
    with pytest.raises(ValueError):
        paginate(_hits(10), page=1, page_size=-5)


# ---------------------------------------------------------------------------
# SearchResultPage model
# ---------------------------------------------------------------------------


def test_search_result_page_rejects_hits_exceeding_page_size():
    with pytest.raises(ValidationError):
        SearchResultPage(
            hits=_hits(5),
            page=1,
            page_size=3,
            total_hits=5,
            total_pages=2,
            has_previous=False,
            has_next=True,
        )


def test_search_result_page_rejects_unknown_extra_field():
    with pytest.raises(ValidationError):
        SearchResultPage(
            hits=[],
            page=1,
            page_size=10,
            total_hits=0,
            total_pages=0,
            has_previous=False,
            has_next=False,
            offset=0,
        )


# ---------------------------------------------------------------------------
# End-to-end: semantic + lexical -> merge_and_rank -> paginate
# ---------------------------------------------------------------------------


def test_full_pipeline_semantic_lexical_rank_paginate():
    store = InMemoryVectorStore(
        [
            ("doc-1", [1.0, 0.0]),
            ("doc-2", [0.9, 0.1]),
            ("doc-3", [0.0, 1.0]),
            ("doc-4", [0.1, 0.9]),
        ]
    )
    semantic_hits = semantic_search(
        store, [SemanticQuery(vector=[1.0, 0.0])], top_k=4
    )

    corpus = [
        ("doc-1", "public procurement rules"),
        ("doc-2", "taxation policy"),
        ("doc-3", "public taxation reform"),
        ("doc-4", "weather report"),
    ]
    lexical_hits = lexical_search(corpus, LexicalQuery(first_of=["public"]))

    ranked = merge_and_rank(semantic_hits, lexical_hits)
    page = paginate(ranked, page=1, page_size=2)

    assert page.total_hits == len(ranked)
    assert len(page.hits) == 2
    # "doc-1" is both the strongest semantic match and a lexical match
    # ("public procurement"), so it should lead the ranked, paginated output.
    assert page.hits[0].id == "doc-1"
