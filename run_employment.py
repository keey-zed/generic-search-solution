"""Run the database-backed public-employment search API."""
from __future__ import annotations

import os
from pathlib import Path

from app.api.http import create_http_app
from app.custom.employment.bootstrap import build_search_engine


def main() -> None:
    repository_root = Path(__file__).resolve().parent
    default_db = repository_root / "data" / "employment" / "employment.db"
    db_path = Path(os.environ.get("EMPLOYMENT_DB_PATH", str(default_db)))
    engine = build_search_engine(db_path=db_path)
    app = create_http_app(engine)
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("DEBUG", "1") == "1"
    print(f" * Emploi Public search (SQLite: {db_path}) on http://{host}:{port}")
    print(f" * GET  http://localhost:{port}/api/config")
    print(f" * GET  http://localhost:{port}/api/facets")
    print(f" * POST http://localhost:{port}/api/search")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
