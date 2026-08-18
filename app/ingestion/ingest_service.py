# backend_BO/app/ingestion/ingest_service.py

import json
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

# Kept for compatibility with the rest of the backend.
# We intentionally do NOT reload or mutate the searchable corpus in this placeholder service.
from .. import data_loader  # noqa: F401


# -------------------------------------------------------------------
# Global state
# -------------------------------------------------------------------

INGEST_LOCK = threading.Lock()  # kept for compatibility, unused in dummy mode

# Legal use case for now: PDF only
ALLOWED_EXT = {".pdf"}

JOBS_LOCK = threading.Lock()
JOBS = {}  # job_id -> job dict
JOB_TTL_SECONDS = 60 * 60  # 1 hour


# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------

def _app_root() -> Path:
    # .../backend_BO
    return Path(__file__).resolve().parent.parent.parent


def _books_root_dir() -> Path:
    """
    Backward-compatible name.
    Actual folder:
      backend_BO/data/book_documents
    """
    p = _app_root() / "data" / "book_documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _books_pdf_dir() -> Path:
    """
    Required destination for uploaded legal PDFs:
      backend_BO/data/book_documents/books_pdf
    """
    p = _books_root_dir() / "books_pdf"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _normalize_rel_path(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("/")


# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------

_filename_sanitize_re = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')


def sanitize_filename(name: str) -> str:
    """
    Lightweight filename sanitizer for Windows-safe storage.
    Keeps extension handling to the caller.
    """
    s = (name or "").strip()
    if not s:
        return ""

    s = _filename_sanitize_re.sub("_", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    return s


def _cleanup_old_jobs():
    now = time.time()
    with JOBS_LOCK:
        dead = []
        for jid, job in JOBS.items():
            if now - job.get("created_ts", now) > JOB_TTL_SECONDS:
                dead.append(jid)
        for jid in dead:
            JOBS.pop(jid, None)


def _dedupe_target_path(target_dir: Path, desired_name: str) -> Path:
    """
    Avoid overwriting an existing uploaded PDF.
    """
    target = target_dir / desired_name
    if not target.exists():
        return target

    stem = Path(desired_name).stem
    ext = Path(desired_name).suffix
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return target_dir / f"{stem}_{ts}{ext}"


# -------------------------------------------------------------------
# Upload saving
# -------------------------------------------------------------------

def save_uploads_exact_structure(files) -> tuple[list[Path], list[dict], list[dict]]:
    """
    PDF-only placeholder uploader.

    Saves accepted files to:
      data/book_documents/books_pdf/<filename>.pdf

    Returns:
      saved_abs_paths
      rejected_items: [{name, reason}]
      docs_info: [{doc_key, name, stem, rel_path}]
    """
    target_dir = _books_pdf_dir()

    rejected = []
    saved = []
    docs_info = []

    for f in files:
        filename = (getattr(f, "filename", "") or "").strip()
        if not filename:
            rejected.append({"name": "", "reason": "empty filename"})
            continue

        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            rejected.append({
                "name": filename,
                "reason": f"unsupported extension: {ext} (only .pdf is allowed)"
            })
            continue

        safe_name = sanitize_filename(filename) or "document.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{Path(safe_name).stem}.pdf"

        abs_path = _dedupe_target_path(target_dir, safe_name)
        f.save(str(abs_path))

        rel_under_books = abs_path.relative_to(_books_root_dir())
        rel_norm = _normalize_rel_path(str(rel_under_books))

        saved.append(abs_path)
        docs_info.append({
            "doc_key": rel_norm,
            "name": abs_path.name,
            "stem": Path(abs_path.name).stem,
            "rel_path": rel_norm,
        })

    return saved, rejected, docs_info


# -------------------------------------------------------------------
# Dummy ingestion job creation
# -------------------------------------------------------------------

def start_ingest_job(files) -> dict:
    """
    Called by POST /admin/process.

    Current legal-search behavior:
      - accept only PDFs
      - save them into books_pdf
      - DO NOT process them
      - DO NOT OCR them
      - DO NOT update books_chunks.pickle
      - DO NOT reload data_loader
      - create an immediate finished dummy job for frontend compatibility
    """
    _cleanup_old_jobs()

    saved_paths, rejected, docs_info = save_uploads_exact_structure(files)
    if not saved_paths:
        return {
            "ok": False,
            "message": "No valid PDF files accepted.",
            "rejected": rejected,
            "docs": [],
        }

    job_id = uuid.uuid4().hex
    q = queue.Queue()

    docs = {}
    docs_order = []

    for d in docs_info:
        docs_order.append(d["doc_key"])
        docs[d["doc_key"]] = {
            "doc_key": d["doc_key"],
            "name": d["name"],
            "rel_path": d["rel_path"],
            "status": "done",
            "percent": 100,
            "current_page": 0,
            "total_pages": 0,
            "message": "Upload accepted. Ingestion is disabled for now.",
        }

    result = {
        "message": "PDF upload accepted, but ingestion/processing is disabled for now.",
        "accepted_files": [Path(p).name for p in saved_paths],
        "saved_count": len(saved_paths),
        "processed": False,
        "data_version": getattr(data_loader, "DATA_VERSION", None),
    }

    job = {
        "job_id": job_id,
        "created_ts": time.time(),
        "status": "done",
        "docs": docs,
        "docs_order": docs_order,
        "events": q,
        "result": result,
    }

    with JOBS_LOCK:
        JOBS[job_id] = job

    # Queue some standard events so existing SSE consumers keep working.
    q.put({
        "type": "snapshot",
        "job_id": job_id,
        "docs": [docs[k] for k in docs_order],
        "status": "done",
    })

    for key in docs_order:
        q.put({
            "type": "doc_done",
            "doc_key": key,
            "message": "Upload accepted. Ingestion is disabled for now.",
        })

    q.put({
        "type": "done",
        "message": result["message"],
        "processed": False,
        "data_version": result["data_version"],
    })

    return {
        "ok": True,
        "job_id": job_id,
        "docs": [docs[k] for k in docs_order],
        "rejected": rejected,
        "message": result["message"],
    }


# -------------------------------------------------------------------
# Job inspection
# -------------------------------------------------------------------

def job_snapshot(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_ts": job["created_ts"],
            "docs": [job["docs"][k] for k in job["docs_order"]],
            "result": job.get("result"),
        }


# -------------------------------------------------------------------
# SSE
# -------------------------------------------------------------------

def sse_generator(job_id: str):
    """
    SSE stream for a job.

    Even though jobs are immediate in dummy mode, we preserve the same
    streaming contract used by the frontend.
    """
    snap = job_snapshot(job_id)
    if not snap:
        yield f"data: {json.dumps({'type': 'error', 'message': 'job not found'}, ensure_ascii=False)}\n\n"
        return

    # Send snapshot first
    yield (
        f"data: {json.dumps({'type': 'snapshot', 'job_id': job_id, 'docs': snap['docs'], 'status': snap['status']}, ensure_ascii=False)}\n\n"
    )

    last_keepalive = time.time()

    while True:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                break
            q = job["events"]

        try:
            evt = q.get(timeout=1.0)
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except queue.Empty:
            pass

        now = time.time()
        if now - last_keepalive > 15:
            yield ": keepalive\n\n"
            last_keepalive = now

        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                break
            if job["status"] in ("done", "error") and job["events"].empty():
                break