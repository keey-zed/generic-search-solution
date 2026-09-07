"""
app/embeddings/cache.py

Generic, model-aware on-disk cache for document embeddings, backed by
Hugging Face's `safetensors` format.

Storage format
--------------
One `.safetensors` file per cache: a single "vectors" tensor (float32,
shape `[n_documents, dim]`) plus a small string-keyed header holding
`model_id` and an `index` (a JSON string mapping each document id to its
row number and text digest, for invalidation).

Why safetensors instead of hand-rolled JSON/binary:

  - Faster: the format is designed for zero-copy / mmap loading -- no
    per-value parsing pass like `json.loads` on a huge float list.
  - Lighter: vectors are packed 4-byte floats, not ~15-17 ASCII
    characters per float the way plain JSON would encode them.
  - Safer: unlike pickle-based tensor formats, safetensors cannot
    execute arbitrary code on load, and its header is length-checked
    against the file, so a truncated/corrupted cache fails to load
    cleanly instead of misbehaving.
  - Practical: it's a standard, widely-supported interchange format
    (used throughout the Hugging Face ecosystem) with tooling to
    inspect a cache file outside this project if ever needed, rather
    than a bespoke format only this codebase understands.

A cached vector is only reused when both its document id's text digest
and the cache's model_id match the current embedder -- exactly the same
invalidation contract this cache has always had, just persisted
differently. Switching an existing project from a previous cache format
to this one is transparent: the old file simply fails to parse as
safetensors and is treated as a cache miss, so the corpus is re-embedded
once and the new-format cache is written from then on.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from safetensors import safe_open
from safetensors.numpy import save_file

from app.core.embeddings import TextEmbedder
from app.core.schema.embedding import Embedding
from app.core.schema.metadata_types import NormalizedDocument


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_cache(
    path: Path, model_id: str
) -> tuple[dict[str, dict[str, object]], Optional[np.ndarray]]:
    """Return (index, vectors) for a valid, matching cache, or ({}, None)
    if no usable cache exists yet (missing file, wrong/corrupt format,
    or a different embedding model)."""
    if not path.exists():
        return {}, None
    try:
        with safe_open(str(path), framework="numpy") as handle:
            metadata = handle.metadata() or {}
            if metadata.get("model_id") != model_id:
                return {}, None
            index_raw = metadata.get("index")
            if not index_raw or "vectors" not in handle.keys():
                return {}, None
            try:
                index = json.loads(index_raw)
            except json.JSONDecodeError:
                return {}, None
            if not isinstance(index, dict):
                return {}, None
            vectors = handle.get_tensor("vectors")
    except Exception:
        # Any parse/format problem (truncated file, wrong format, a
        # cache written by a previous version of this module) is a
        # cache miss, never a crash.
        return {}, None
    return index, vectors


def load_or_create_document_embeddings(
    documents: Iterable[NormalizedDocument],
    embedder: TextEmbedder,
    *,
    cache_path: str | Path | None = None,
) -> dict[str, Embedding]:
    """Return embeddings for documents, reusing matching cached vectors.

    A cached vector is valid only when both its document id/text digest and
    model id match. Changed or new documents are embedded in one batch
    (the embedder is not called at all if nothing is missing); removed
    documents disappear from the rewritten cache. Omitting ``cache_path``
    keeps the operation entirely in memory.
    """
    document_list = list(documents)
    documents_by_id = {document.id: document for document in document_list}
    if len(documents_by_id) != len(document_list):
        raise ValueError("cannot create embeddings for duplicate document ids")

    path = Path(cache_path) if cache_path is not None else None
    index, cached_vectors = _read_cache(path, embedder.model_id) if path is not None else ({}, None)

    resolved: dict[str, Embedding] = {}
    missing: list[NormalizedDocument] = []

    for document in document_list:
        digest = _text_digest(document.text)
        entry = index.get(document.id)
        row = entry.get("row") if isinstance(entry, dict) else None
        if (
            cached_vectors is not None
            and isinstance(entry, dict)
            and entry.get("text_sha256") == digest
            and isinstance(row, int)
            and 0 <= row < cached_vectors.shape[0]
        ):
            resolved[document.id] = Embedding(
                vector=[float(x) for x in cached_vectors[row]], model_id=embedder.model_id
            )
            continue
        missing.append(document)

    if missing:
        vectors = embedder.embed_documents([document.text for document in missing])
        if len(vectors) != len(missing):
            raise RuntimeError(
                f"text embedder returned {len(vectors)} vectors for {len(missing)} documents"
            )
        for document, vector in zip(missing, vectors, strict=True):
            resolved[document.id] = Embedding(vector=vector, model_id=embedder.model_id)

    if path is not None:
        ordered_ids = sorted(resolved)
        dim = len(resolved[ordered_ids[0]].vector) if ordered_ids else 0
        matrix = np.zeros((len(ordered_ids), dim), dtype=np.float32)
        new_index: dict[str, dict[str, object]] = {}
        for row, doc_id in enumerate(ordered_ids):
            vector = resolved[doc_id].vector
            if len(vector) != dim:
                raise ValueError(
                    f"embedding cache: document '{doc_id}' has {len(vector)} dimensions, "
                    f"expected {dim} -- all vectors sharing one cache/model must be the same size"
                )
            matrix[row] = vector
            new_index[doc_id] = {"row": row, "text_sha256": _text_digest(documents_by_id[doc_id].text)}

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
        os.close(fd)
        try:
            save_file(
                {"vectors": matrix},
                temporary_name,
                metadata={"model_id": embedder.model_id, "index": json.dumps(new_index, ensure_ascii=False)},
            )
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    return resolved
