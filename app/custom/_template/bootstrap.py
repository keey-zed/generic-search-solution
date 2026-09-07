"""
app/custom/_template/bootstrap.py

STEP 4: wiring. You typically do NOT need to edit this file -- it is the
generic glue that turns config.yaml + raw_loader.py + custom_filters.py
(+ optionally precomputed embeddings) into one ready-to-use
`SearchEngine` (app.api.orchestrator.SearchEngine). Copy it as-is into
your project's folder; customize the other three files instead.

    config.yaml  +  raw_loader.load_raw_records()  +  custom_filters.CUSTOM_FILTERS
                              |
                              v
                    build_search_engine()
                              |
                              v
                        SearchEngine  --.search(SearchRequest)-->  SearchResultPage

This function does not silently paper over a dirty ingestion run (some
raw records failed validation/typing, or had duplicate ids) -- it raises
instead of quietly starting with fewer documents than you think you
have. See the docstring below for what to do about that; a real
project's actual choice (log and continue vs. refuse to start vs. alert
an operator) is a judgment call this template deliberately leaves to
you, since it depends on how mission-critical this deployment is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from app.api import SearchEngine
from app.core.config.loader import load_use_case_config
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider, TextEmbedder
from app.core.ingestion import ingest_raw_records
from app.embeddings import load_or_create_document_embeddings

from . import custom_filters, raw_loader  # noqa: F401 -- swap the package per project

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def build_search_engine(
    *,
    config_path: Union[str, Path] = _DEFAULT_CONFIG_PATH,
    embedding_provider: Optional[EmbeddingProvider] = None,
    text_embedder: Optional[TextEmbedder] = None,
    embeddings_cache_path: Optional[Union[str, Path]] = None,
) -> SearchEngine:
    """Build a working `SearchEngine` for this project.

    Args:
        config_path: defaults to this project's own config.yaml,
            sitting alongside this file. Override only if you need to
            point at a different config at runtime (e.g. per-environment
            configs).
        embedding_provider: optional, for projects using a fully custom
            embedding storage strategy (e.g. a vector DB). Pass this OR
            text_embedder, not both.
        text_embedder: optional. Pass your own `TextEmbedder` to embed
            `raw_loader`'s text (typically built once from this
            project's own `config.yaml` via
            `app.embeddings.build_text_embedder(config.search.semantic.embedder)`
            -- see app/core/config/models.py:EmbedderConfig and
            run_factory.py for the full pattern). If omitted entirely,
            any inline embedding already present on an ingested document
            (V1 storage, see app/core/schema/embedding.py) is still
            picked up automatically. Deliberately NOT built here from
            config.yaml automatically: that would force every caller of
            this function -- including lightweight tests exercising only
            lexical search/filtering -- to have the embedding runtime
            installed.
        embeddings_cache_path: optional on-disk cache location for
            `text_embedder`'s vectors. Pass
            `config.search.semantic.embedder.cache_path` yourself if you
            want the config's declared cache location used.

    Raises:
        app.api.errors.BadConfigError: config.yaml itself is invalid, or
            its filters (generic or custom-overridden) can't be built.
        ValueError: ingestion reported problems with the raw data --
            see the message for what to inspect
            (`report.record_errors` / `report.duplicate_ids`) and how to
            proceed deliberately instead of silently continuing.
    """
    config = load_use_case_config(config_path)
    schema = config.to_metadata_schema()

    raw_records = raw_loader.load_raw_records()
    report = ingest_raw_records(raw_records, schema)

    if not report.is_clean:
        raise ValueError(
            f"ingestion reported problems, refusing to start with unclean "
            f"data ({report.summary}). Inspect report.record_errors / "
            f"report.duplicate_ids, fix the raw data at the source, or "
            f"explicitly choose to proceed with only report.valid_documents "
            f"if that's an acceptable outcome for this project."
        )

    documents = report.valid_documents

    if text_embedder is not None:
        if embedding_provider is not None:
            raise ValueError("pass either text_embedder or embedding_provider, not both")
        embeddings = load_or_create_document_embeddings(
            documents, text_embedder, cache_path=embeddings_cache_path
        )
        documents = [
            document.model_copy(update={"embedding": embeddings[document.id]})
            for document in documents
        ]
        embedding_provider = InlineEmbeddingProvider(documents)
    elif embedding_provider is None and any(doc.embedding is not None for doc in documents):
        embedding_provider = InlineEmbeddingProvider(documents)

    return SearchEngine.from_config_path(
        config_path,
        documents,
        custom_filters=custom_filters.CUSTOM_FILTERS,
        embedding_provider=embedding_provider,
        text_embedder=text_embedder,
    )