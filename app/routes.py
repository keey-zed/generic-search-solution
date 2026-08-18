# backend_BO/app/routes.py

from flask import (
    Blueprint,
    request,
    jsonify,
    send_file,
    Response,
    stream_with_context,
    url_for,
)
from . import data_loader
from .services import search_fuzzy, get_valid_indices, get_filter_options

import time
import math
import io
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from werkzeug.utils import secure_filename

from .semantic_engine import SemanticEngine

main_bp = Blueprint("main", __name__)

# -----------------------------
# Semantic search helpers
# -----------------------------
_SEM_ENGINE_SINGLETON = None
_SEM_ENGINE_INIT_ERROR = None

# -----------------------------
# Dummy admin upload job store
# -----------------------------
_DUMMY_ADMIN_JOBS = {}


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _coerce_opt_int(v, default=None):
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _clamp_int(v, default, min_v=None, max_v=None):
    try:
        v = int(v)
    except Exception:
        v = default
    if min_v is not None and v < min_v:
        v = min_v
    if max_v is not None and v > max_v:
        v = max_v
    return v


def _get_semantic_engine():
    """
    Lazy singleton to avoid loading heavy models at app startup.
    Forces engine.load() on first semantic request so init errors are explicit.
    """
    global _SEM_ENGINE_SINGLETON, _SEM_ENGINE_INIT_ERROR

    if _SEM_ENGINE_SINGLETON is not None:
        return _SEM_ENGINE_SINGLETON

    if _SEM_ENGINE_INIT_ERROR is not None:
        raise RuntimeError(_SEM_ENGINE_INIT_ERROR)

    if SemanticEngine is None:
        _SEM_ENGINE_INIT_ERROR = "SemanticEngine import failed. Check app/semantic_engine.py dependencies."
        raise RuntimeError(_SEM_ENGINE_INIT_ERROR)

    try:
        eng = SemanticEngine()
        eng.load()
        _SEM_ENGINE_SINGLETON = eng
        return _SEM_ENGINE_SINGLETON
    except Exception as e:
        _SEM_ENGINE_INIT_ERROR = f"Failed to initialize SemanticEngine: {e}"
        raise RuntimeError(_SEM_ENGINE_INIT_ERROR)


# Warm semantic engine at backend startup (keeps existing behavior)
try:
    _get_semantic_engine()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("SemanticEngine startup warmup failed: %s", e)


def _unique_preserve_order(seq):
    out = []
    seen = set()
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _parse_queries_from_args(args, is_semantic=False):
    """
    GET parser for /search-advanced.

    Non-semantic:
      - qs[]=...
      - q=... split by \n into multiple entries

    Semantic:
      - one logical query only
      - preserve line breaks inside the query
      - if qs[] has many values, join them with '\n'
    """
    qs = args.getlist("qs")
    q_single_raw = args.get("q", "")

    if is_semantic:
        if qs:
            joined = "\n".join([str(x) for x in qs if str(x).strip()])
            return [joined.strip()] if joined.strip() else []
        q = "" if q_single_raw is None else str(q_single_raw)
        return [q.strip()] if q.strip() else []

    q_single = (q_single_raw or "").strip()
    if qs:
        queries = [x.strip() for x in qs if str(x).strip()]
    elif q_single:
        if "\n" in q_single:
            queries = [x.strip() for x in q_single.split("\n") if x.strip()]
        else:
            queries = [q_single]
    else:
        queries = []

    return _unique_preserve_order(queries)


def _parse_queries_from_json(data: dict, is_semantic: bool | None = None):
    """
    Non-semantic:
      - supports data['queries'] as multi-entry
      - splits data['query'] by newline into multiple entries

    Semantic:
      - forces a SINGLE query entry
      - preserves line breaks inside the query text
      - if 'queries' has many entries, joins them by '\n'
    """
    if is_semantic is None:
        is_semantic = bool(data.get("isSemanticSearch", False))

    queries_raw = data.get("queries")
    raw_list = []
    if isinstance(queries_raw, (list, tuple, set)):
        raw_list = [str(x) for x in queries_raw if str(x).strip()]

    q_single_raw = data.get("query")
    q_single = "" if q_single_raw is None else str(q_single_raw)

    if is_semantic:
        if raw_list:
            joined = "\n".join([x for x in raw_list if x.strip()])
            return [joined.strip()] if joined.strip() else []
        return [q_single.strip()] if q_single.strip() else []

    queries = [x.strip() for x in raw_list if x.strip()]

    if not queries and q_single.strip():
        q = q_single.strip()
        if "\n" in q:
            queries = [x.strip() for x in q.split("\n") if x.strip()]
        else:
            queries = [q]

    return _unique_preserve_order(queries)


def _sanitize_source_ranges(ranges, text_len: int):
    """
    Normalize and clip source_ranges to valid [start, end) slices.
    Accepts tuples/lists or dicts with start/end.
    """
    out = []

    if not isinstance(ranges, (list, tuple)):
        return out

    for r in ranges:
        a = b = None

        if isinstance(r, dict):
            a = r.get("start")
            b = r.get("end")
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            a, b = r[0], r[1]
        else:
            continue

        try:
            a = int(a)
            b = int(b)
        except Exception:
            continue

        if b < a:
            a, b = b, a

        a = max(0, min(text_len, a))
        b = max(0, min(text_len, b))

        if b <= a:
            continue

        out.append((a, b))

    if not out:
        return []

    out.sort(key=lambda x: (x[0], x[1]))

    merged = [out[0]]
    for a, b in out[1:]:
        la, lb = merged[-1]
        if a <= lb:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))

    return merged


def _run_semantic_search(query: str, valid_indices, k: int = 300000):
    """
    Returns CHUNK-level hits from SemanticEngine.search(), but:
      - if valid_indices is None or equals the full corpus: global search
      - otherwise: auto-tune inside the filtered subset via search_in_pages()
    """
    q = (query or "")
    if not q.strip():
        return [], []

    engine = _get_semantic_engine()

    if valid_indices is None:
        chunk_hits = list(engine.search(q, k=int(k)))
        return chunk_hits, []

    valid_list = list(valid_indices)
    if len(valid_list) == 0:
        return [], []

    if len(valid_list) >= len(data_loader.chunks):
        chunk_hits = list(engine.search(q, k=int(k)))
        return chunk_hits, []

    chunk_hits = list(engine.search_in_pages(q, valid_page_indices=valid_list, k=int(k)))
    return chunk_hits, []


def _paginate(items, page, page_size):
    total = len(items)
    if total == 0:
        return [], {
            "page": page,
            "page_size": page_size,
            "total_results": 0,
            "total_pages": 0,
            "has_prev": False,
            "has_next": False,
        }

    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    return page_items, {
        "page": page,
        "page_size": page_size,
        "total_results": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def _build_item(idx: int, source_ranges=None, semantic_score=None, matched_chunk_indices=None):
    return {
        "id": idx,
        "chunk": data_loader.chunks[idx],
        "filename": data_loader.filenames[idx],
        "page_number": data_loader.page_numbers[idx],
        "subjects": data_loader.subjects_list[idx],
        "signatures": data_loader.signatures_list[idx],
        "doctype": data_loader.doctypes[idx],
        "lawnumber": data_loader.lawnumbers[idx],
        "date": data_loader.dates[idx],
        "path": data_loader.paths[idx],
        "source_ranges": source_ranges or [],
        **({"semantic_score": semantic_score} if semantic_score is not None else {}),
        **({"matched_chunk_indices": matched_chunk_indices or []} if matched_chunk_indices is not None else {}),
    }


def _build_items(result_indices):
    return [_build_item(idx) for idx in result_indices]


def _aggregate_chunk_hits_to_pages(chunk_hits):
    """
    Convert chunk-level semantic hits into page-level hits.

    Rules:
      - multiple chunks can map to the same page_index
      - keep best semantic_score per page
      - merge source_ranges across chunks for that page
    """
    by_page = {}

    for hit in chunk_hits:
        if not isinstance(hit, dict):
            continue

        page_idx = _coerce_opt_int(hit.get("page_index"), default=None)
        if page_idx is None:
            continue

        page_text = ""
        if 0 <= page_idx < len(data_loader.chunks):
            page_text = data_loader.chunks[page_idx] or ""

        text_len = len(page_text)
        sr = _sanitize_source_ranges(hit.get("source_ranges", []), text_len=text_len)

        try:
            score = float(hit.get("semantic_score", 0.0))
        except Exception:
            score = 0.0

        row = by_page.get(page_idx)
        if row is None:
            by_page[page_idx] = {
                "page_index": page_idx,
                "semantic_score": score,
                "source_ranges": list(sr),
                "matched_chunk_indices": [hit.get("chunk_index")],
            }
        else:
            if score > float(row.get("semantic_score", 0.0)):
                row["semantic_score"] = score

            cidx = hit.get("chunk_index")
            if cidx is not None:
                row["matched_chunk_indices"].append(cidx)

            row["source_ranges"].extend(sr)

    out = []
    for page_idx, row in by_page.items():
        page_text = data_loader.chunks[page_idx] if 0 <= page_idx < len(data_loader.chunks) else ""
        merged = _sanitize_source_ranges(row.get("source_ranges", []), text_len=len(page_text))
        row["source_ranges"] = merged

        uniq = []
        seen = set()
        for x in row.get("matched_chunk_indices", []):
            try:
                xi = int(x)
            except Exception:
                continue
            if xi not in seen:
                seen.add(xi)
                uniq.append(xi)
        row["matched_chunk_indices"] = uniq

        out.append(row)

    out.sort(key=lambda x: float(x.get("semantic_score", 0.0)), reverse=True)
    return out


def _build_semantic_items_from_pages(page_hits):
    out = []

    for hit in page_hits:
        page_idx = _coerce_opt_int(hit.get("page_index"), default=None)
        if page_idx is None or not (0 <= page_idx < len(data_loader.chunks)):
            continue

        out.append(
            _build_item(
                page_idx,
                source_ranges=hit.get("source_ranges", []),
                semantic_score=hit.get("semantic_score", 0.0),
                matched_chunk_indices=hit.get("matched_chunk_indices", []),
            )
        )

    return out


def _filters_from_json(data: dict):
    """
    Legal filter contract.

    Supported:
      - mandatoryKeywords
      - filename
      - subjects
      - signatures
      - doctype
      - lawnumber
      - date / date_from / date_to / dateFrom / dateTo

    Backward-compatible pass-throughs:
      - topics
      - bookName
    """
    filters = {
        "isSemanticSearch": _to_bool(data.get("isSemanticSearch", False)),
        "mandatoryKeywords": data.get("mandatoryKeywords") or [],
        "filename": data.get("filename"),
        "subjects": data.get("subjects") if data.get("subjects") is not None else (data.get("topics") or []),
        "signatures": data.get("signatures"),
        "doctype": data.get("doctype"),
        "lawnumber": data.get("lawnumber"),
    }

    date_obj = data.get("date")
    if isinstance(date_obj, dict):
        date_from = date_obj.get("from")
        date_to = date_obj.get("to")
    else:
        date_from = data.get("date_from", data.get("dateFrom"))
        date_to = data.get("date_to", data.get("dateTo"))

    if date_obj is not None:
        filters["date"] = date_obj
    if date_from is not None:
        filters["date_from"] = date_from
    if date_to is not None:
        filters["date_to"] = date_to

    # backward-compatible alias
    if filters["filename"] is None and data.get("bookName") is not None:
        filters["filename"] = data.get("bookName")

    return filters


def _has_active_filters(filters: dict):
    return any(
        [
            bool(filters.get("mandatoryKeywords")),
            bool(filters.get("filename")),
            bool(filters.get("subjects")),
            bool(filters.get("signatures")),
            bool(filters.get("doctype")),
            bool(filters.get("lawnumber")),
            bool(filters.get("date")),
            bool(filters.get("date_from")),
            bool(filters.get("date_to")),
        ]
    )


def _compute_all_result_indices(data: dict):
    """
    Same logic as /search-with-filters, but returns ALL results (no pagination).

    Semantic export returns PAGE indices aligned with data_loader.
    """
    filters = _filters_from_json(data)
    queries = _parse_queries_from_json(data, is_semantic=filters.get("isSemanticSearch", False))

    if not queries and not _has_active_filters(filters):
        return [], [], filters

    valid_indices = get_valid_indices(filters)

    if queries:
        if filters.get("isSemanticSearch", False):
            semantic_query = queries[0]
            chunk_hits, expanded_queries = _run_semantic_search(semantic_query, valid_indices)
            page_hits = _aggregate_chunk_hits_to_pages(chunk_hits)

            result_indices = []
            for hit in page_hits:
                pidx = _coerce_opt_int(hit.get("page_index"))
                if pidx is not None:
                    result_indices.append(pidx)

            return result_indices, expanded_queries, filters

        query_payload = queries if len(queries) > 1 else queries[0]
        result_indices, expanded_queries = search_fuzzy(query_payload, valid_indices)
        return result_indices, expanded_queries, filters

    result_indices = list(valid_indices)
    result_indices.sort()
    return result_indices, [], filters


def _safe_filename_part(s: str, fallback="export"):
    s = (s or "").strip()
    if not s:
        return fallback
    s = re.sub(r"[^\w\u0600-\u06FF\s\-]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:80] if s else fallback


def _page_sort_key(p):
    try:
        return (0, int(p))
    except Exception:
        return (1, str(p or ""))


def _safe_abs_from_rel(rel_path: str) -> Path:
    """
    Prevent path traversal. Ensure resolved path stays inside documents_root_dir().
    """
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    root = data_loader.documents_root_dir().resolve()
    abs_path = (root / rel_path).resolve()
    if root not in abs_path.parents and abs_path != root:
        raise ValueError("Unsafe path")
    return abs_path


def _dummy_upload_root() -> Path:
    root = data_loader.documents_root_dir().resolve().parent / "books_pdf"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _create_dummy_job(saved_files, rejected):
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    job_id = f"dummy-{ts}"
    snap = {
        "job_id": job_id,
        "status": "completed",
        "stage": "disabled",
        "progress": 100,
        "message": "Upload accepted. Ingestion is disabled for now; no processing was executed.",
        "docs": saved_files,
        "rejected": rejected,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": datetime.utcnow().isoformat() + "Z",
    }
    _DUMMY_ADMIN_JOBS[job_id] = snap
    return snap


def _dummy_sse_generator(job_id):
    snap = _DUMMY_ADMIN_JOBS.get(job_id)
    if not snap:
        yield 'event: error\ndata: {"error":"job not found"}\n\n'
        return

    payload = jsonify(snap).get_data(as_text=True)
    yield f"event: progress\ndata: {payload}\n\n"
    yield f"event: done\ndata: {payload}\n\n"


@main_bp.route("/", methods=["GET"])
def status():
    return jsonify(
        {
            "status": "ok",
            "chunks_loaded": len(data_loader.chunks),
            "documents_loaded": len({p for p in data_loader.paths if p}),
            "data_version": getattr(data_loader, "DATA_VERSION", None),
        }
    )


@main_bp.route("/search-advanced", methods=["GET"])
def searchadvanced():
    t0 = time.time()

    is_semantic = _to_bool(
        request.args.get("isSemanticSearch", request.args.get("semantic", False))
    )

    queries = _parse_queries_from_args(request.args, is_semantic=is_semantic)
    if not queries:
        return jsonify({"error": "Missing query"}), 400

    page = _clamp_int(request.args.get("page", 1), default=1, min_v=1)
    page_size = _clamp_int(request.args.get("page_size", 30), default=30, min_v=1, max_v=200)

    valid_indices = list(range(len(data_loader.chunks)))

    if is_semantic:
        try:
            semantic_query = queries[0]
            chunk_hits, expanded_queries = _run_semantic_search(semantic_query, valid_indices)

            page_hits = _aggregate_chunk_hits_to_pages(chunk_hits)
            total_unique_pages = len(page_hits)

            page_hits_page, page_meta = _paginate(page_hits, page, page_size)

            page_meta["total_results"] = total_unique_pages
            page_meta["total_pages"] = max(1, math.ceil(total_unique_pages / page_size)) if total_unique_pages else 0
            page_meta["has_prev"] = page_meta["page"] > 1
            page_meta["has_next"] = page_meta["page"] < page_meta["total_pages"]

            payload = {
                "results": _build_semantic_items_from_pages(page_hits_page),
                "expanded_queries": expanded_queries,
                "original_query": semantic_query,
                "original_queries": [semantic_query],
                "endpoint": "search-advanced",
                "isSemanticSearch": True,
                **page_meta,
                "server_seconds": round(time.time() - t0, 3),
            }
            return jsonify(payload)

        except Exception as e:
            return jsonify({"error": f"Semantic search failed: {e}"}), 500

    query_payload = queries if len(queries) > 1 else queries[0]
    result_indices, expanded_queries = search_fuzzy(query_payload, valid_indices)

    page_indices, page_meta = _paginate(result_indices, page, page_size)

    payload = {
        "results": _build_items(page_indices),
        "expanded_queries": expanded_queries,
        "original_query": " OR ".join(queries),
        "original_queries": queries,
        "endpoint": "search-advanced",
        "isSemanticSearch": False,
        **page_meta,
        "server_seconds": round(time.time() - t0, 3),
    }
    return jsonify(payload)


@main_bp.route("/search-with-filters", methods=["POST"])
def searchwithfilters():
    t0 = time.time()

    data = request.get_json(silent=True) or {}
    filters = _filters_from_json(data)
    queries = _parse_queries_from_json(data, is_semantic=filters["isSemanticSearch"])

    page = _clamp_int(data.get("page", 1), default=1, min_v=1)
    page_size = _clamp_int(data.get("page_size", 30), default=30, min_v=1, max_v=200)

    if not queries and not _has_active_filters(filters):
        return jsonify({"error": "Missing query or filters"}), 400

    valid_indices = get_valid_indices(filters)

    if queries and filters["isSemanticSearch"]:
        try:
            semantic_query = queries[0]
            chunk_hits, expanded_queries = _run_semantic_search(semantic_query, valid_indices)

            page_hits = _aggregate_chunk_hits_to_pages(chunk_hits)
            total_unique_pages = len(page_hits)

            page_hits_page, page_meta = _paginate(page_hits, page, page_size)

            page_meta["total_results"] = total_unique_pages
            page_meta["total_pages"] = max(1, math.ceil(total_unique_pages / page_size)) if total_unique_pages else 0
            page_meta["has_prev"] = page_meta["page"] > 1
            page_meta["has_next"] = page_meta["page"] < page_meta["total_pages"]

            payload = {
                "results": _build_semantic_items_from_pages(page_hits_page),
                "expanded_queries": expanded_queries,
                "original_query": semantic_query,
                "original_queries": [semantic_query],
                "endpoint": "search-with-filters",
                "valid_after_filters": len(valid_indices),
                "filters": filters,
                "isSemanticSearch": True,
                **page_meta,
                "server_seconds": round(time.time() - t0, 3),
            }
            return jsonify(payload)

        except Exception as e:
            return jsonify({"error": f"Semantic search failed: {e}"}), 500

    if queries:
        query_payload = queries if len(queries) > 1 else queries[0]
        result_indices, expanded_queries = search_fuzzy(query_payload, valid_indices)
        original_query = " OR ".join(queries)
        original_queries = queries
    else:
        result_indices = list(valid_indices)
        result_indices.sort()
        expanded_queries = []
        original_query = ""
        original_queries = []

    page_indices, page_meta = _paginate(result_indices, page, page_size)

    payload = {
        "results": _build_items(page_indices),
        "expanded_queries": expanded_queries,
        "original_query": original_query,
        "original_queries": original_queries,
        "endpoint": "search-with-filters",
        "valid_after_filters": len(valid_indices),
        "filters": filters,
        "isSemanticSearch": False,
        **page_meta,
        "server_seconds": round(time.time() - t0, 3),
    }
    return jsonify(payload)


@main_bp.route("/chunk/<int:chunk_id>", methods=["GET"])
def get_chunk(chunk_id):
    if chunk_id < 0 or chunk_id >= len(data_loader.chunks):
        return jsonify({"error": "Chunk ID not found"}), 404
    return jsonify(_build_item(chunk_id))


@main_bp.route("/file/<path:rel_path>", methods=["GET"])
def serve_file(rel_path):
    try:
        abs_path = _safe_abs_from_rel(rel_path)
    except Exception:
        return jsonify({"error": "Unsafe path"}), 400

    if not abs_path.exists():
        return jsonify({"error": "File not found"}), 404

    return send_file(str(abs_path), as_attachment=False)


@main_bp.route("/open/<int:chunk_id>", methods=["GET"])
def open_document(chunk_id):
    """
    PDF-only opening logic for legal documents.
    """
    if chunk_id < 0 or chunk_id >= len(data_loader.chunks):
        return jsonify({"error": "Invalid chunk ID"}), 404

    rel_path = data_loader.paths[chunk_id]
    page_number = data_loader.page_numbers[chunk_id]

    if not rel_path:
        return jsonify({"error": "Missing path for this chunk"}), 400
        
    if not Path(rel_path).suffix:
        rel_path = f"{rel_path}.pdf"

    try:
        abs_path = _safe_abs_from_rel(rel_path)
    except Exception:
        return jsonify({"error": "Unsafe path"}), 400

    if not abs_path.exists():
        return jsonify({"error": "File not found", "expected_path": str(abs_path)}), 404

    if abs_path.suffix.lower() != ".pdf":
        return jsonify({"error": "Only PDF documents are supported"}), 400

    file_url = url_for("main.serve_file", rel_path=rel_path.replace("\\", "/"), _external=True)

    return jsonify(
        {
            "type": "pdf",
            "file_url": file_url,
            "page": page_number,
            "filename": data_loader.filenames[chunk_id],
            "doctype": data_loader.doctypes[chunk_id],
            "lawnumber": data_loader.lawnumbers[chunk_id],
            "date": data_loader.dates[chunk_id],
            "path": rel_path,
        }
    )


# ============================================================
# EXPORT
# ============================================================

@main_bp.route("/export/full", methods=["POST"])
def export_full():
    """
    TXT export grouped by filename, including legal metadata.
    """
    data = request.get_json(silent=True) or {}
    indices, expanded, filters = _compute_all_result_indices(data)

    doc_map = defaultdict(list)
    doc_meta = {}

    for i in indices:
        filename = data_loader.filenames[i] or "document"
        page_number = data_loader.page_numbers[i]
        txt = (data_loader.chunks[i] or "").strip()

        doc_map[filename].append((page_number, txt))

        if filename not in doc_meta:
            doc_meta[filename] = {
                "doctype": data_loader.doctypes[i] or "",
                "lawnumber": data_loader.lawnumbers[i] or "",
                "date": data_loader.dates[i] or "",
                "subjects": data_loader.subjects_list[i] or [],
                "signatures": data_loader.signatures_list[i] or [],
                "path": data_loader.paths[i] or "",
            }

    docs_sorted = sorted(doc_map.keys(), key=lambda x: str(x or "").lower())

    lines = []
    qs = _parse_queries_from_json(data, is_semantic=_to_bool(data.get("isSemanticSearch", False)))
    header = " / ".join(qs) if qs else "بدون كلمات بحث"

    lines.append("FULL EXPORT")
    lines.append(f"QUERY: {header}")
    lines.append(f"TOTAL RESULTS: {len(indices)}")
    lines.append("")

    for filename in docs_sorted:
        meta = doc_meta.get(filename, {})
        lines.append(f"FILENAME: {filename}")
        lines.append(f"DOCTYPE: {meta.get('doctype', '')}")
        lines.append(f"LAWNUMBER: {meta.get('lawnumber', '')}")
        lines.append(f"DATE: {meta.get('date', '')}")
        lines.append(f"SUBJECTS: {', '.join(meta.get('subjects', []))}")
        lines.append(f"SIGNATURES: {', '.join(meta.get('signatures', []))}")
        lines.append(f"PATH: {meta.get('path', '')}")
        lines.append("")

        items = sorted(doc_map[filename], key=lambda x: _page_sort_key(x[0]))

        for page_number, txt in items:
            lines.append(f"PAGE: {page_number if page_number is not None else '-'}")
            lines.append(txt)
            lines.append("---")
            lines.append("")

        lines.append("######")
        lines.append("")

    content = "\n".join(lines).encode("utf-8")
    bio = io.BytesIO(content)
    bio.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = _safe_filename_part(" / ".join(qs), fallback="نتائج")
    filename = f"full_export_{name_part}_{ts}.txt"

    return send_file(
        bio,
        as_attachment=True,
        download_name=filename,
        mimetype="text/plain; charset=utf-8",
    )


# ============================================================
# ADMIN - dummy PDF upload only
# ============================================================

ALLOWED_ADMIN_EXT = {".pdf"}


@main_bp.route("/admin/status", methods=["GET"])
def admin_status():
    return jsonify(
        {
            "status": "ok",
            "message": "Admin endpoints are active. Ingestion is disabled; PDF upload is accepted in dummy mode only.",
            "chunks_loaded": len(data_loader.chunks),
            "documents_loaded": len({p for p in data_loader.paths if p}),
            "data_version": getattr(data_loader, "DATA_VERSION", None),
        }
    )


@main_bp.route("/admin/process", methods=["POST"])
def admin_process():
    """
    Dummy upload endpoint:
      - accepts PDF files only
      - saves them in a dummy upload folder
      - does NOT trigger OCR, ingestion, corpus merge, or embedding updates
      - returns an immediately completed fake job_id for frontend compatibility
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded. Use field name 'files'."}), 400

    usable = []
    rejected = []

    for f in files:
        name = (f.filename or "").strip()
        if not name:
            rejected.append({"name": "", "reason": "empty filename"})
            continue

        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_ADMIN_EXT:
            rejected.append({"name": name, "reason": f"unsupported extension: {ext} (only .pdf)"})
            continue

        usable.append(f)

    if not usable:
        return jsonify(
            {
                "status": "error",
                "message": "No valid files accepted.",
                "rejected": rejected,
            }
        ), 400

    saved_files = []
    upload_root = _dummy_upload_root()
    timestamp_prefix = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")

    for idx, f in enumerate(usable, start=1):
        original_name = (f.filename or "").strip()
        safe_name = secure_filename(original_name) or f"upload_{idx}.pdf"
        final_name = f"{timestamp_prefix}_{idx}_{safe_name}"
        save_path = upload_root / final_name
        f.save(str(save_path))

        saved_files.append(
            {
                "original_name": original_name,
                "stored_name": final_name,
                "stored_path": str(save_path),
                "size_bytes": save_path.stat().st_size if save_path.exists() else None,
            }
        )

    snap = _create_dummy_job(saved_files=saved_files, rejected=rejected)

    return jsonify(
        {
            "status": "ok",
            "message": "Upload accepted. Ingestion is disabled for now; no processing was executed.",
            "job_id": snap["job_id"],
            "docs": saved_files,
            "rejected": rejected,
        }
    )


@main_bp.route("/admin/progress/<job_id>", methods=["GET"])
def admin_progress(job_id):
    """
    Dummy SSE endpoint for compatibility with existing frontend flow.
    """
    headers = {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    }
    return Response(stream_with_context(_dummy_sse_generator(job_id)), headers=headers)


@main_bp.route("/admin/job/<job_id>", methods=["GET"])
def admin_job(job_id):
    snap = _DUMMY_ADMIN_JOBS.get(job_id)
    if not snap:
        return jsonify({"error": "job not found"}), 404
    return jsonify(snap)


# ============================================================
# FILTER OPTIONS
# ============================================================

@main_bp.route("/filters/options", methods=["GET"])
def filters_options():
    try:
        opts = get_filter_options()
        return jsonify(
            {
                **opts,
                "data_version": getattr(data_loader, "DATA_VERSION", None),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route("/filters/books", methods=["GET"])
def filters_books():
    """
    Backward-compatible alias.
    Returns legal filenames under the historical route.
    """
    try:
        opts = get_filter_options()
        books = opts.get("filenames", [])
        return jsonify(
            {
                "books": books,
                "count": len(books),
                "data_version": getattr(data_loader, "DATA_VERSION", None),
                "deprecated": True,
                "replacement": "/filters/options",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# ADMIN DOCUMENT SUMMARY / UPDATE
# ============================================================

@main_bp.route("/admin/documents/summary", methods=["GET"])
def admin_documents_summary():
    try:
        return jsonify({"status": "ok", **data_loader.compute_documents_summary()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/admin/documents/update", methods=["POST"])
def admin_documents_update():
    """
    Body:
      {
        "filename": "...",
        "doctype": "...",        # optional
        "lawnumber": "...",      # optional
        "date": "...",           # optional
        "subjects": [...],       # optional
        "signatures": [...],     # optional
        "path": "..."            # optional
      }

    Updates all rows belonging to the same filename.
    """
    data = request.get_json(silent=True) or {}

    filename = (data.get("filename") or "").strip()
    if not filename:
        return jsonify({"status": "error", "message": "filename is required"}), 400

    doctype = data.get("doctype", None)
    lawnumber = data.get("lawnumber", None)
    date_val = data.get("date", None)
    subjects = data.get("subjects", None)
    signatures = data.get("signatures", None)
    path_val = data.get("path", None)

    if doctype is not None and len(str(doctype)) > 250:
        return jsonify({"status": "error", "message": "doctype is too long"}), 400
    if lawnumber is not None and len(str(lawnumber)) > 250:
        return jsonify({"status": "error", "message": "lawnumber is too long"}), 400
    if date_val is not None and len(str(date_val)) > 120:
        return jsonify({"status": "error", "message": "date is too long"}), 400
    if path_val is not None and len(str(path_val)) > 1000:
        return jsonify({"status": "error", "message": "path is too long"}), 400

    try:
        res = data_loader.update_document_metadata(
            filename=filename,
            new_doctype=doctype,
            new_lawnumber=lawnumber,
            new_date=date_val,
            new_subjects=subjects,
            new_signatures=signatures,
            new_path=path_val,
        )
        return jsonify({"status": "ok", **res})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# DEPRECATED BOOK ADMIN ALIASES
# ============================================================

@main_bp.route("/admin/books/summary", methods=["GET"])
def admin_books_summary():
    """
    Deprecated compatibility route.
    Returns the new document summary payload shape.
    """
    try:
        return jsonify(
            {
                "status": "ok",
                "deprecated": True,
                "replacement": "/admin/documents/summary",
                **data_loader.compute_documents_summary(),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/admin/books/update", methods=["POST"])
def admin_books_update():
    """
    Deprecated compatibility route.
    Accepts old 'book_name' key and maps it to filename.
    """
    data = request.get_json(silent=True) or {}

    filename = (data.get("filename") or data.get("book_name") or "").strip()
    if not filename:
        return jsonify({"status": "error", "message": "filename (or book_name) is required"}), 400

    doctype = data.get("doctype", data.get("category"))
    lawnumber = data.get("lawnumber")
    date_val = data.get("date")
    subjects = data.get("subjects")
    signatures = data.get("signatures")
    path_val = data.get("path")

    try:
        res = data_loader.update_document_metadata(
            filename=filename,
            new_doctype=doctype,
            new_lawnumber=lawnumber,
            new_date=date_val,
            new_subjects=subjects,
            new_signatures=signatures,
            new_path=path_val,
        )
        return jsonify(
            {
                "status": "ok",
                "deprecated": True,
                "replacement": "/admin/documents/update",
                **res,
            }
        )
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500