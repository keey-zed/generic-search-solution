"""Generic, file-backed *extraction* helpers for custom ingestion layers.

This module intentionally sits outside :mod:`app.core`.  ``core`` accepts
the stable ``{id, text, metadata}`` wire format and must not depend on a
particular file type or on PyMuPDF.  A use case can use these helpers to
turn a directory of PDFs into that wire format, then pass the result to
``core.ingestion.ingest_raw_records`` as usual.

The extractor does not try to guess legal concepts from a filename or a
page.  Source-specific metadata is supplied by the calling custom layer,
which keeps the same extractor usable for contracts, manuals, case law, or
any other PDF corpus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping


@dataclass(frozen=True)
class FileExtractionIssue:
    """One non-fatal problem encountered while reading a source file."""

    path: Path
    message: str
    page_number: int | None = None
    severity: Literal["warning", "error"] = "error"


@dataclass
class PdfExtractionReport:
    """Raw records and a complete accounting of a PDF extraction run."""

    records: list[dict[str, Any]] = field(default_factory=list)
    issues: list[FileExtractionIssue] = field(default_factory=list)
    files_seen: int = 0
    pages_seen: int = 0

    @property
    def is_clean(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _as_pdf_paths(sources: Path | str | Iterable[Path | str], *, recursive: bool) -> list[Path]:
    candidates = [sources] if isinstance(sources, (str, Path)) else list(sources)
    paths: list[Path] = []
    for source in candidates:
        path = Path(source)
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            paths.extend(
                candidate
                for candidate in iterator
                if candidate.is_file() and candidate.suffix.lower() == ".pdf"
            )
        elif path.is_file() and path.suffix.lower() == ".pdf":
            paths.append(path)
    return sorted(set(paths), key=lambda candidate: str(candidate).casefold())


def _source_key(path: Path, source_root: Path | None) -> str:
    if source_root is not None:
        try:
            return path.relative_to(source_root).as_posix()
        except ValueError:
            pass
    return path.name


def extract_pdf_records(
    sources: Path | str | Iterable[Path | str],
    *,
    metadata_by_source: Mapping[str, Mapping[str, Any]] | None = None,
    default_metadata: Mapping[str, Any] | None = None,
    recursive: bool = True,
    empty_page_policy: Literal["skip", "include", "error"] = "skip",
) -> PdfExtractionReport:
    """Extract native text from PDFs as one searchable record per page.

    ``metadata_by_source`` may be keyed by either a path relative to a
    supplied directory (``issues/BO_7000.pdf``) or just a filename.  The
    relative key wins, then the filename.  Its values are merged over
    ``default_metadata``.  The caller owns the metadata vocabulary and
    validation; this function merely preserves it in core's flat wire
    format, adding the generic provenance fields ``source_path``,
    ``source_file``, and ``source_page``.

    Empty/scanned pages are never silently mistaken for indexed text:
    by default they are skipped and reported as warnings.  Set
    ``empty_page_policy='error'`` to make them extraction errors or
    ``'include'`` to retain an empty record for metadata-only searches.
    OCR is deliberately a separate, opt-in source concern; this avoids
    hidden network calls or fabricated text during ingestion.

    Raises:
        ValueError: if ``empty_page_policy`` is invalid.
        RuntimeError: if PyMuPDF is not installed.  Install the project's
            ``legacy-app`` extra (or PyMuPDF directly) in the environment
            that performs PDF extraction.
    """
    if empty_page_policy not in {"skip", "include", "error"}:
        raise ValueError("empty_page_policy must be 'skip', 'include', or 'error'")

    try:
        import fitz  # PyMuPDF is deliberately an optional extraction dependency.
    except ImportError as exc:  # pragma: no cover - depends on installation choice
        raise RuntimeError(
            "PDF extraction requires PyMuPDF. Install it with `pip install PyMuPDF` "
            "or install this project's `legacy-app` extra."
        ) from exc

    source_root: Path | None = None
    if isinstance(sources, (str, Path)) and Path(sources).is_dir():
        source_root = Path(sources).resolve()

    defaults = dict(default_metadata or {})
    overrides = metadata_by_source or {}
    report = PdfExtractionReport()

    for path in _as_pdf_paths(sources, recursive=recursive):
        report.files_seen += 1
        resolved_path = path.resolve()
        source_key = _source_key(resolved_path, source_root)
        supplied_metadata = overrides.get(source_key, overrides.get(path.name, {}))
        if not isinstance(supplied_metadata, Mapping):
            report.issues.append(
                FileExtractionIssue(
                    path=path,
                    message="metadata override must be an object/map; file was not indexed",
                )
            )
            continue

        try:
            document = fitz.open(str(path))
        except Exception as exc:
            report.issues.append(FileExtractionIssue(path=path, message=f"could not open PDF: {exc}"))
            continue

        try:
            for page_index in range(len(document)):
                page_number = page_index + 1
                report.pages_seen += 1
                try:
                    text = (document.load_page(page_index).get_text("text") or "").strip()
                except Exception as exc:
                    report.issues.append(
                        FileExtractionIssue(
                            path=path,
                            page_number=page_number,
                            message=f"could not extract page text: {exc}",
                        )
                    )
                    continue

                if not text:
                    severity: Literal["warning", "error"] = (
                        "error" if empty_page_policy == "error" else "warning"
                    )
                    report.issues.append(
                        FileExtractionIssue(
                            path=path,
                            page_number=page_number,
                            severity=severity,
                            message=(
                                "page has no embedded text (it may be scanned and require OCR)"
                            ),
                        )
                    )
                    if empty_page_policy != "include":
                        continue

                metadata = {
                    **defaults,
                    **dict(supplied_metadata),
                    "source_path": source_key,
                    "source_file": path.name,
                    "source_page": page_number,
                }
                report.records.append(
                    {
                        "id": f"{source_key}#page={page_number}",
                        "text": text,
                        "metadata": metadata,
                    }
                )
        finally:
            document.close()

    return report
