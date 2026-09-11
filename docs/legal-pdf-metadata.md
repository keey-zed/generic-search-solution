# Legal PDF metadata

The legal PDF loader indexes one Bulletin Officiel PDF page at a time. It
always supplies `source_file`, `source_page`, `file_name`, and
`document_type`. For selectable-text pages, the legal custom layer also makes
a conservative first-pass extraction of `issue_number`, `publication_date`,
`document_type`, `law_number`, `promulgation_date`, `subjects`, and
`signatures`. Act metadata is carried across continuation pages, while
sidecar values remain authoritative.

This is a heuristic extraction pass, not a legal metadata authority. A
Bulletin Officiel issue can contain several laws, dates, and signers, and
Arabic PDF text can contain extraction noise. Scanned pages still require
OCR and are skipped by the native-text extractor.

To provide those project-specific fields, create a JSON sidecar keyed by PDF
filename or a path relative to the PDF root, then start the server with
`LEGAL_METADATA_PATH` set to that file. Use
`app/custom/legal/metadata.example.json` as the shape reference. Sidecar values
are merged into every page record belonging to that source PDF.
