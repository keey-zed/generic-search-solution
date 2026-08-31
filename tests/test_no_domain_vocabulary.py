"""
tests/test_no_domain_vocabulary.py

Retrieval Definition of Done: "No use-case field names appear anywhere in
this code."

This is not a one-time audit -- it's a permanent regression test that
scans the actual source files under app/core/search/ (never test files,
which are free to use realistic example data) for vocabulary specific to
any one use case. If a future change to semantic/, lexical/, ranking/,
or pagination/ accidentally imports domain knowledge (a field name, a
use-case name, a piece of legal/book/justice-specific vocabulary), this
test fails immediately and names the offending file and term, rather
than relying on someone noticing in review.

The blocklist is deliberately drawn from two places, so it's grounded in
concrete examples rather than a guess at what "domain-specific" means:

  1. The source doc's own §9 example metadata fields for the two
     example domains it names (legal search vs. book search) --
     exactly the fields the generic engine "does not need dedicated
     code for."
  2. The roadmap's own list of example/future search applications
     (§11) -- "Justice Search," "Bulletin Officiel Search," "Book
     Search," "Administrative Document Search," "Public Employment
     Search."

Matches are case-insensitive and use word boundaries so "author" doesn't
false-positive on some unrelated identifier, but "authoritative" would
still be flagged if a term is later added that could plausibly match it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SEARCH_CORE_ROOT = Path(__file__).resolve().parent.parent / "app" / "core" / "search"

# Source doc §9: example metadata fields for legal-search and book-search
# use cases -- the two domains the architecture doc uses throughout as
# its running examples of "what the generic engine must NOT know about."
LEGAL_DOMAIN_TERMS = [
    "promulgation_date",
    "publication_date",
    "document_type",
    "issuing_authority",
    "cross_references",
    "jurisdiction",
]
BOOK_DOMAIN_TERMS = [
    "author",
    "volume",
    "chapter",
    "source_collection",
]
# Roadmap §11: named example/future search applications.
USE_CASE_NAMES = [
    "legal search",
    "justice search",
    "bulletin officiel",
    "book search",
    "administrative document",
    "public employment",
]

ALL_BLOCKED_TERMS = LEGAL_DOMAIN_TERMS + BOOK_DOMAIN_TERMS + USE_CASE_NAMES


def _search_core_source_files():
    assert SEARCH_CORE_ROOT.is_dir(), f"expected {SEARCH_CORE_ROOT} to exist"
    return sorted(SEARCH_CORE_ROOT.rglob("*.py"))


def test_search_core_has_source_files_to_check():
    # Guards against this test silently passing because the glob matched
    # nothing (e.g. the module got moved and SEARCH_CORE_ROOT is stale).
    assert len(_search_core_source_files()) >= 4


@pytest.mark.parametrize("term", ALL_BLOCKED_TERMS)
def test_search_core_contains_no_domain_vocabulary(term):
    pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
    offenders = []
    for path in _search_core_source_files():
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path.relative_to(SEARCH_CORE_ROOT.parent.parent.parent)))

    assert not offenders, (
        f"found use-case-specific term '{term}' in generic search core "
        f"file(s): {offenders} -- this violates Retrieval's Definition of "
        f"Done ('No use-case field names appear anywhere in this code')"
    )
