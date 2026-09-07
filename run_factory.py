"""
run_factory.py

Entrypoint for the Generic Search Factory's HTTP layer (app/api/http.py).

This does exactly what the legacy app's run.py did for the old artisan
app: build a fully-configured SearchEngine, wrap it in a Flask app via
create_http_app(), and start a dev server -- so it behaves like "any
normal app" you can run and immediately hit from Postman or a frontend.

Usage:
    pip install -e ".[http,legacy-app]"
    python run_factory.py

Then:
    GET  http://localhost:5000/api/health
    POST http://localhost:5000/api/search

By default this serves the real PDFs in
``data/legal_documents/documents_pdf`` through the legal custom layer. Set
``LEGAL_DOCUMENTS_DIR`` to point at another folder and optionally set
``LEGAL_METADATA_PATH`` to a per-file JSON metadata sidecar. Documents
and raw semantic queries are embedded with the configured local
SentenceTransformer model; vectors are cached between restarts.
"""
from __future__ import annotations

import os
from pathlib import Path
from app.api.http import create_http_app
from app.core.config.loader import load_use_case_config
from app.custom.legal.bootstrap import _DEFAULT_CONFIG_PATH, build_search_engine
from app.custom.legal.source_resolver import build_pdf_source_resolver
from app.embeddings import build_text_embedder


def build_engine():
    """Build the legal SearchEngine.

    Only the data *location* is an environment concern (where the PDFs
    / metadata sidecar happen to live on this machine) -- everything
    about the embedding model itself (which model, prefixes, device,
    batch size, cache location) is declared once in
    app/custom/legal/config.yaml under `search.semantic.embedder` and
    read from there below. See app/core/config/models.py:EmbedderConfig.
    """
    repository_root = Path(__file__).resolve().parent
    source_candidates = [
        repository_root / "data" / "legal_documents" / "documents_pdf",
    ]
    default_documents_dir = next(
        (candidate for candidate in source_candidates if candidate.is_dir()), source_candidates[0]
    )
    documents_dir = os.environ.get("LEGAL_DOCUMENTS_DIR", str(default_documents_dir))
    metadata_path = os.environ.get("LEGAL_METADATA_PATH")

    config = load_use_case_config(_DEFAULT_CONFIG_PATH)
    embedder_config = config.search.semantic.embedder if config.search.semantic.enabled else None
    text_embedder = build_text_embedder(embedder_config) if embedder_config is not None else None
    cache_path = embedder_config.cache_path if embedder_config is not None else None

    engine = build_search_engine(
        documents_dir=documents_dir,
        metadata_path=metadata_path,
        text_embedder=text_embedder,
        embeddings_cache_path=cache_path,
    )
    return engine, Path(documents_dir)


def main() -> None:
    engine, documents_dir = build_engine()
    app = create_http_app(
        engine,
        source_file_resolver=build_pdf_source_resolver(documents_dir),
    )

    host = os.environ.get("HOST", "0.0.0.0")  # 0.0.0.0 so it's reachable from other machines/devices too
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "1") == "1"

    print(f" * Generic Search Factory (PDF corpus) serving on http://{host}:{port}")
    print(f" * Try: GET  http://localhost:{port}/api/health")
    print(f" * Try: GET  http://localhost:{port}/api/config")
    print(f" * Try: GET  http://localhost:{port}/api/facets")
    print(f" * Try: POST http://localhost:{port}/api/search")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
