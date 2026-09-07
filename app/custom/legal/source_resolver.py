"""Map legal PDF-page records back to files without leaking path policy to core."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.schema.metadata_types import NormalizedDocument


def build_pdf_source_resolver(documents_dir: str | Path):
    """Build a resolver restricted to PDF files below ``documents_dir``.

    The extractor provides ``source_path`` and ``source_file`` as metadata.
    They are trusted only after the resolved path is proven to remain inside
    this project's configured source root.
    """
    root = Path(documents_dir).resolve()

    def resolve(document: NormalizedDocument) -> Optional[Path]:
        source = document.metadata.get("source_path") or document.metadata.get("source_file")
        if not isinstance(source, str) or not source.strip():
            return None

        candidate = (root / source).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.suffix.lower() == ".pdf" else None

    return resolve
