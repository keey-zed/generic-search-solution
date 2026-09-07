"""
app/embeddings/factory.py

Builds a concrete `TextEmbedder` from a use case's declarative
`search.semantic.embedder` config (`app.core.config.models.EmbedderConfig`),
so a new use case only has to edit its `config.yaml` -- never Python -- to
pick a model, its query/document prefixes, device, batch size, or on-disk
cache location.

Lives outside `app.core` for the same reason `sentence_transformer.py`
does: it is allowed to import concrete, potentially heavy ML adapters
that the generic core must never depend on. Adding a new provider means
adding a branch here (and a matching literal in `EmbedderProvider`) --
never touching `app.core` or any use case's bootstrap.
"""
from __future__ import annotations

from app.core.config.models import EmbedderConfig
from app.core.embeddings.provider import TextEmbedder


def build_text_embedder(config: EmbedderConfig) -> TextEmbedder:
    """Instantiate the `TextEmbedder` described by `config`.

    Raises `ValueError` for an unrecognized `provider` -- this should
    only happen if `EmbedderProvider`'s literal values and this
    function's branches have drifted apart (see module docstring).
    """
    if config.provider == "sentence_transformer":
        from .sentence_transformer import SentenceTransformerTextEmbedder

        return SentenceTransformerTextEmbedder(
            config.model,
            device=config.device,
            batch_size=config.batch_size,
            document_prefix=config.document_prefix,
            query_prefix=config.query_prefix,
        )
    raise ValueError(f"unknown embedder provider: {config.provider!r}")
