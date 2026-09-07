# app/ingestion/__init__.py
"""Source-side ingestion helpers.

Unlike :mod:`app.core.ingestion`, this package may know about input
formats (for example PDFs) and application integration details.
"""

from .file_records import FileExtractionIssue, PdfExtractionReport, extract_pdf_records

__all__ = ["FileExtractionIssue", "PdfExtractionReport", "extract_pdf_records"]
