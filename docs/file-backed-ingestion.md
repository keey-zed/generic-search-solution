# File-backed ingestion

`app/core/ingestion` remains the generic validation and normalization
boundary. Reading a file is source extraction, so it belongs in a custom
layer. The legal custom layer now exposes that path for the existing
Bulletin Officiel PDFs.

Run the HTTP API against the bundled BO directory:

```powershell
pip install -e ".[http,legacy-app]"
python run_factory.py
```

The default source directory is `data/legal_documents/documents_pdf`, resolved
relative to `run_factory.py` rather than the terminal's current folder.

The server indexes native PDF text as one record per page. Search it with
a lexical request, for example:

```json
{
  "lexical": {"first_of": ["المادة", "مرسوم"]},
  "page_size": 20
}
```

The frontend integration endpoints are:

- `GET /api/config` — resolved branding, visible filters, supported search
  modes, result-card fields, and pagination limits.
- `GET /api/facets` — values/counts for selectable filters and populated date
  bounds. A frontend should disable or hide a control whose
  `available_count` is zero.
- `POST /api/search` — paginated hits; each includes `document_url` and, in
  the runnable legal server, `source_url` for the source PDF/page.
- `GET /api/documents/<id>` — full indexed page text and metadata.
- `GET /api/documents/<id>/source` — source PDF, exposed only through the
  legal resolver, which confines access to `LEGAL_DOCUMENTS_DIR`.

A result id has the stable form
`BO_6720-bis_Ar.pdf#page=3`; its metadata includes `source_file`,
`source_path`, and `source_page`, so a frontend can open the original
file at the matching page.

To point at another directory, set `LEGAL_DOCUMENTS_DIR`. PDFs may have a
`metadata.json` sidecar in that directory (or set `LEGAL_METADATA_PATH`)
to provide source-authoritative metadata. It is an object keyed by either
the PDF filename or its relative path:

```json
{
  "BO_6720-bis_Ar.pdf": {
    "title": "Bulletin Officiel n° 6720 bis",
    "publication_date": "2018-10-01",
    "subjects": ["fiscalite", "administration"]
  }
}
```

`document_type` defaults to `bulletin_officiel`; a sidecar value replaces
it. This is deliberately data/configuration, not a legal-specific rule in
the extractor. No dates, titles, legal status, or subjects are guessed
from the filename.

The extractor reports empty pages as warnings and does not index them.
That usually means a scanned PDF and requires an OCR stage before those
pages are searchable. It never silently calls a remote OCR service.
The runnable server also performs semantic search using the same local
`SentenceTransformer` model for documents and queries. The default is the
same multilingual E5 model used by the legacy semantic engine; its vectors
are cached in `data/embeddings/legal.safetensors`. Embedder settings live in
`app/custom/legal/config.yaml`. The first startup
downloads/loads the selected model and embeds uncached pages; later
starts reuse unchanged vectors. Send raw text rather than a
client-generated vector:

```json
{"semantic_text": ["conditions de passation des marchés publics"]}
```

`semantic` with precomputed numeric vectors remains supported for clients
that already have their own query embedder. `semantic_text` is the normal
Postman/frontend payload when this server owns the embedding model.
