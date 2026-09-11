"""Build the public-employment SearchEngine from a relational database."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from app.api import SearchEngine
from app.core.config.loader import load_use_case_config
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider, TextEmbedder
from app.core.ingestion import ingest_raw_records
from app.embeddings import load_or_create_document_embeddings

from . import custom_filters
from .db_raw_loader import load_raw_records_from_db

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "employment" / "employment.db"


def build_search_engine(
    *,
    config_path: Union[str, Path] = _DEFAULT_CONFIG_PATH,
    db_path: Optional[Union[str, Path]] = _DEFAULT_DB_PATH,
    embedding_provider: Optional[EmbeddingProvider] = None,
    text_embedder: Optional[TextEmbedder] = None,
    embeddings_cache_path: Optional[Union[str, Path]] = None,
) -> SearchEngine:
    """Build the employment engine from SQLite.

    The database is loaded once at startup; requests use the generic in-memory
    filtering and lexical search pipeline. Pass ``db_path`` for another DB.
    """
    if db_path is None:
        raise ValueError("db_path is required for the database-backed employment use case")
    if text_embedder is not None and embedding_provider is not None:
        raise ValueError("pass either text_embedder or embedding_provider, not both")

    config = load_use_case_config(config_path)
    report = ingest_raw_records(load_raw_records_from_db(db_path), config.to_metadata_schema())
    if not report.is_clean:
        raise ValueError(
            "employment database ingestion reported problems, refusing to start "
            f"with unclean data ({report.summary}). Inspect "
            "report.record_errors / report.duplicate_ids."
        )

    documents = report.valid_documents
    if text_embedder is not None:
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
