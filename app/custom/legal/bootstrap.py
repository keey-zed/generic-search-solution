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
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider
from app.core.ingestion import ingest_raw_records

from . import custom_filters, raw_loader

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def build_search_engine(
    *,
    config_path: Union[str, Path] = _DEFAULT_CONFIG_PATH,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> SearchEngine:
    """Build a working `SearchEngine` for the legal project. See
    app/custom/_template/bootstrap.py's docstring for the full contract
    -- this is that same function, unmodified in behavior."""
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

    if embedding_provider is None and any(doc.embedding is not None for doc in report.valid_documents):
        embedding_provider = InlineEmbeddingProvider(report.valid_documents)

    return SearchEngine.from_config_path(
        config_path,
        report.valid_documents,
        custom_filters=custom_filters.CUSTOM_FILTERS,
        embedding_provider=embedding_provider,
    )