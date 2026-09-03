"""
run.py

Entrypoint for the Generic Search Factory's HTTP layer (app/api/http.py).

This does exactly what the legacy app's run.py did for the old artisan
app: build a fully-configured SearchEngine, wrap it in a Flask app via
create_http_app(), and start a dev server -- so it behaves like "any
normal app" you can run and immediately hit from Postman or a frontend.

Usage:
    pip install -e ".[http]"
    python run.py

Then:
    GET  http://localhost:5000/api/health
    POST http://localhost:5000/api/search

Uses the legal_pilot use case (app/custom/legal_pilot/) as the engine
being served, since it's the one reference build that already exists
end-to-end in this repo. Swap the config path / raw_loader import below
if you want to serve a different use case instead.

Note: the embeddings below are randomly generated placeholders, purely
so semantic search has *something* to search against. Replace
InlineEmbeddingProvider's input with your real embeddings pipeline
before this is anything more than a local smoke-test server.
"""
from __future__ import annotations

import os
import random

from app.api import SearchEngine
from app.api.http import create_http_app
from app.core.config import load_use_case_config
from app.core.embeddings.provider import InlineEmbeddingProvider
from app.core.ingestion import ingest_raw_records
from app.core.schema.embedding import Embedding, EmbeddedDocumentRecord
from app.custom.legal_pilot.raw_loader import load_raw_records

CONFIG_PATH = "app/custom/legal_pilot/config.yaml"


def _fake_embedding(seed: int, dim: int = 4) -> Embedding:
    """Placeholder embedding generator -- see module docstring."""
    rng = random.Random(seed)
    return Embedding(
        vector=[rng.uniform(-1, 1) for _ in range(dim)],
        model_id="dev-placeholder-embedder-v0",
    )


def build_engine() -> SearchEngine:
    config = load_use_case_config(CONFIG_PATH)
    report = ingest_raw_records(load_raw_records(), config.to_metadata_schema())
    if not report.is_clean:
        # Fail loudly rather than silently serving a partial index.
        raise RuntimeError(f"ingestion produced invalid records: {report.summary}")

    embeddings = {doc.id: _fake_embedding(hash(doc.id)) for doc in report.valid_documents}
    embedding_provider = InlineEmbeddingProvider(
        [
            EmbeddedDocumentRecord(
                id=doc.id, text=doc.text, metadata={}, embedding=embeddings[doc.id]
            )
            for doc in report.valid_documents
        ]
    )

    return SearchEngine.from_config_path(
        CONFIG_PATH,
        report.valid_documents,
        custom_filters={},
        embedding_provider=embedding_provider,
    )


def main() -> None:
    engine = build_engine()
    app = create_http_app(engine)  # CORS on by default -- any frontend origin can call it

    host = os.environ.get("HOST", "0.0.0.0")  # 0.0.0.0 so it's reachable from other machines/devices too
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "1") == "1"

    print(f" * Generic Search Factory (legal_pilot) serving on http://{host}:{port}")
    print(f" * Try: GET  http://localhost:{port}/api/health")
    print(f" * Try: POST http://localhost:{port}/api/search")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
