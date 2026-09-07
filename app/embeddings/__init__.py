"""Concrete embedding adapters and cache helpers.

These live outside ``app.core`` because they may depend on a particular
model runtime.  They implement the generic ``TextEmbedder`` contract.
"""

from .cache import load_or_create_document_embeddings
from .factory import build_text_embedder
from .sentence_transformer import SentenceTransformerTextEmbedder

__all__ = [
    "SentenceTransformerTextEmbedder",
    "build_text_embedder",
    "load_or_create_document_embeddings",
]
