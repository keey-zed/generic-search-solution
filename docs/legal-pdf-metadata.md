# Legal PDF metadata

The legal PDF loader indexes one Bulletin Officiel PDF page at a time. It
always supplies `source_file`, `source_page`, `file_name`, and
`document_type`. It does not guess a law number, dates, subjects, or signatures
from an issue filename or arbitrary page text: a Bulletin Officiel issue can
contain several laws, dates, and signers.

To provide those project-specific fields, create a JSON sidecar keyed by PDF
filename or a path relative to the PDF root, then start the server with
`LEGAL_METADATA_PATH` set to that file. Use
`app/custom/legal/metadata.example.json` as the shape reference. Sidecar values
are merged into every page record belonging to that source PDF.
