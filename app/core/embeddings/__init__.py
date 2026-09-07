"""Generic embedding contracts and in-memory vector lookup."""

from .provider import EmbeddingProvider, InlineEmbeddingProvider, TextEmbedder

__all__ = ["EmbeddingProvider", "InlineEmbeddingProvider", "TextEmbedder"]
