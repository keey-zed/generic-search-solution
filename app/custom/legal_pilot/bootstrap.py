"""
app/custom/legal_pilot/bootstrap.py

A near-verbatim copy of app/custom/_template/bootstrap.py, pointed at
this project's own config.yaml/raw_loader.py/custom_filters.py -- per
the template's own instructions ("you typically do NOT need to edit
this file"). This is exactly what adopting the template for a real
project looks like in practice.

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
from app.core.embeddings.provider import EmbeddingProvider, InlineEmbeddingProvider
from app.core.ingestion import ingest_raw_records

from . import custom_filters, raw_loader  # noqa: F401 -- swap the package per project

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def build_search_engine(
    *,
    config_path: Union[str, Path] = _DEFAULT_CONFIG_PATH,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> SearchEngine:
    """Build a working `SearchEngine` for this project.

    Args:
        config_path: defaults to this project's own config.yaml,
            sitting alongside this file. Override only if you need to
            point at a different config at runtime (e.g. per-environment
            configs).
        embedding_provider: optional. If omitted AND any ingested
            document carries an inline embedding (V1 storage, see
            docs/ingestion.md / app/core/schema/embedding.py), one is
            built automatically from the ingested batch. Pass your own
            if you're using a different embedding storage strategy.

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

    if embedding_provider is None and any(doc.embedding is not None for doc in report.valid_documents):
        embedding_provider = InlineEmbeddingProvider(report.valid_documents)

    return SearchEngine.from_config_path(
        config_path,
        report.valid_documents,
        custom_filters=custom_filters.CUSTOM_FILTERS,
        embedding_provider=embedding_provider,
    )