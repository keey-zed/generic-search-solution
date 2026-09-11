"""Create the demo SQLite database for the public-employment pilot."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def create_database(db_path: str | Path, *, force: bool = False) -> Path:
    path = Path(db_path)
    if path.exists() and not force:
        raise FileExistsError(f"database already exists: {path}; pass --force to replace it")
    if path.exists():
        if not path.is_file():
            raise IsADirectoryError(f"database path is not a file: {path}")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).resolve().parents[1] / "data" / "employment" / "employment_seed.sql"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=str(Path(__file__).resolve().parents[1] / "data" / "employment" / "employment.db"),
    )
    parser.add_argument("--force", action="store_true", help="replace an existing demo database")
    args = parser.parse_args()
    path = create_database(args.db_path, force=args.force)
    print(f"Created employment demo database: {path}")


if __name__ == "__main__":
    main()
