#!/usr/bin/env python3
"""
Regenerate app/core/schema/document.schema.json from the DocumentRecord
Pydantic model, so the checked-in JSON Schema can never silently drift
from the Python source of truth.

Run this any time app/core/schema/document.py changes, and commit the
diff. CI should run this and fail the build if it produces a diff that
wasn't committed (see docs/metadata-typing.md, "Keeping the JSON Schema
in sync").

Usage: python scripts/regenerate_json_schema.py
(run from the repo root, so the `app` package is importable)
"""
import json
from pathlib import Path

from app.core.schema.document import document_record_json_schema

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "core" / "schema" / "document.schema.json"
)


def main() -> None:
    schema = document_record_json_schema()
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["$id"] = "https://internal/schemas/document-record.schema.json"
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
