"""
app/custom/legal/bootstrap.py

A near-verbatim copy of app/custom/_template/bootstrap.py, pointed at
this project's own config.yaml/raw_loader.py/custom_filters.py -- per
the template's own instructions ("you typically do NOT need to edit
this file"). This is exactly what adopting the template for a real
project looks like in practice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from app.api import SearchEngine
from app.core.config.loader import load_use_case_config
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider, TextEmbedder
from app.core.ingestion import ingest_raw_records
from app.embeddings import load_or_create_document_embeddings

from . import custom_filters, raw_loader
from .db_raw_loader import load_raw_records_from_db

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def build_search_engine(
    *,
    config_path: Union[str, Path] = _DEFAULT_CONFIG_PATH,
    embedding_provider: Optional[EmbeddingProvider] = None,
    text_embedder: Optional[TextEmbedder] = None,
    documents_dir: Optional[Union[str, Path]] = None,
    metadata_path: Optional[Union[str, Path]] = None,
    db_path: Optional[Union[str, Path]] = None,
    embeddings_cache_path: Optional[Union[str, Path]] = None,
) -> SearchEngine:
    """Build the legal engine from the sample corpus, real PDF files, or
    a SQLite database.

    Pass ``documents_dir`` to index PDFs one page at a time (see
    raw_loader.py). Pass ``db_path`` instead to read the same shape of
    records from a SQLite database produced by
    scripts/migrate_legal_pdfs_to_sqlite.py -- see db_raw_loader.py.
    These are mutually exclusive; passing neither uses the small
    embedded sample corpus (raw_loader.py's default). ``metadata_path``
    only applies to the ``documents_dir`` path -- a DB-backed corpus's
    metadata already lives in the database itself (baked in at
    migration time); there is no separate sidecar to apply on top of it.
    """
    if documents_dir is not None and db_path is not None:
        raise ValueError("pass either documents_dir or db_path, not both")
    config = load_use_case_config(config_path)
    schema = config.to_metadata_schema()

    if db_path is not None:
        raw_records = load_raw_records_from_db(db_path)
    else:
        raw_records = raw_loader.load_raw_records(documents_dir, metadata_path=metadata_path)
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
    # NOTE: this function never auto-builds a text_embedder from
    # config.search.semantic.embedder itself -- doing so unconditionally
    # would force every caller (including the lightweight sample-corpus
    # tests in tests/test_custom_layer_template.py) to have
    # sentence-transformers installed just to exercise lexical
    # search/filtering. A caller that wants the config-declared embedder
    # (e.g. run_factory.py, a real deployment) builds it explicitly with
    # `app.embeddings.build_text_embedder(config.search.semantic.embedder)`
    # and passes it in as `text_embedder` -- see run_factory.py.
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