import os
import pickle
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# -------------------------------------------------------------------
# Stable module-level containers
# IMPORTANT: keep the SAME list objects forever to avoid stale refs
# -------------------------------------------------------------------

# Core searchable page corpus
chunks = []
page_numbers = []
paths = []

# Legal metadata
filenames = []
subjects_list = []
signatures_list = []
doctypes = []
lawnumbers = []
dates = []           # raw ISO string as stored/displayed
dates_parsed = []    # parsed datetime or None

# -------------------------------------------------------------------
# Compatibility aliases for the old book-based code
# These aliases intentionally point to meaningful legal equivalents
# so old code does not crash immediately while routes are refactored.
# -------------------------------------------------------------------
book_names = filenames                 # old "book_name" -> new filename
Subject_list = subjects_list           # old Subjects -> new subjects
categories = doctypes                  # closest old analogue
printed_page_numbers = page_numbers    # no separate printed page concept now

# authors has no equivalent in the legal schema, but keep it aligned
authors = []

# Incremented whenever data is reloaded/updated
DATA_VERSION = 0


# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
def _app_root() -> Path:
    # app/ is inside backend_BO/app, so parent is backend_BO
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return _app_root() / "data"


def _chunks_pickle_path() -> Path:
    # backend_BO/data/books_chunks.pickle
    # Kept as-is because your current project description indicates
    # the main page corpus pickle still lives here for now.
    return data_dir() / "books_chunks.pickle"


def documents_root_dir() -> Path:
    # New legal PDFs location
    return data_dir() / "book_documents" / "books_pdf"


def get_document_abs_path(rel_path: str) -> Path:
    return documents_root_dir() / _normalize_rel_path(rel_path)


# Backward-compatible names
def books_root_dir() -> Path:
    return documents_root_dir()


def get_book_abs_path(rel_path: str) -> Path:
    return get_document_abs_path(rel_path)


# -------------------------------------------------------------------
# Coercion / normalization helpers
# -------------------------------------------------------------------
def _normalize_rel_path(p) -> str:
    """
    Normalize a relative file path for URL + filesystem join:
      - convert backslashes to slashes
      - strip leading slashes
      - keep it relative
    """
    if p is None:
        return ""
    s = str(p).strip().replace("\\", "/")
    s = s.lstrip("/")
    return s


def _coerce_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _coerce_str_list(v):
    """
    Ensures metadata fields are always list[str].

    Accepts:
      - None
      - str
      - list / tuple / set
      - mixed values

    Also splits common separators when a single string contains many items.
    """
    if v is None:
        return []

    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s)
        return out

    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        seps = [";", ",", "|", "،", "\n", "\t"]
        for sep in seps:
            if sep in s:
                parts = [p.strip() for p in s.split(sep)]
                return [p for p in parts if p]
        return [s]

    s = str(v).strip()
    return [s] if s else []


def _coerce_page_number(v):
    """
    Keep page_number flexible:
      - int if clean integer
      - stripped string otherwise
      - None if empty
    """
    if v is None:
        return None

    if isinstance(v, int):
        return v

    s = str(v).strip()
    if not s:
        return None

    try:
        return int(s)
    except Exception:
        return s


def _parse_iso_datetime(v):
    """
    Parse legal ISO date strings safely.

    Supported examples:
      - 2018-08-16T00:00:00.000Z
      - 2018-08-16T00:00:00Z
      - 2018-08-16T00:00:00+00:00
      - 2018-08-16

    Returns:
      datetime (timezone-aware when possible) or None
    """
    if v is None:
        return None

    s = str(v).strip()
    if not s:
        return None

    # Normalize trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Try full ISO first
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    # Try date-only
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _choose_path(item: dict, filename: str) -> str:
    """
    Path priority:
      1) explicit item['path']
      2) item['filename']
      3) empty string
    """
    raw_path = _coerce_str(item.get("path"))
    if raw_path:
        return _normalize_rel_path(raw_path)

    if filename:
        return _normalize_rel_path(filename)

    return ""


# -------------------------------------------------------------------
# Core load
# -------------------------------------------------------------------
def load_chunks():
    """
    Loads the legal corpus pickle into module-level lists.

    Expected legal fields per record:
      - filename
      - text
      - page_number
      - subjects
      - signatures
      - doctype
      - lawnumber
      - date
      - path (optional)

    IMPORTANT:
      We mutate lists in-place to avoid stale references in other modules.
    """
    global DATA_VERSION

    pickle_path = _chunks_pickle_path()
    if not pickle_path.exists():
        raise FileNotFoundError(f"Pickle not found: {pickle_path}")

    with open(pickle_path, "rb") as f:
        data = pickle.load(f) or []

    new_chunks = []
    new_page_numbers = []
    new_paths = []

    new_filenames = []
    new_subjects_list = []
    new_signatures_list = []
    new_doctypes = []
    new_lawnumbers = []
    new_dates = []
    new_dates_parsed = []

    new_authors = []  # compatibility only

    for item in data:
        text = item.get("text", "")
        filename = _coerce_str(item.get("filename"))
        page_number = _coerce_page_number(item.get("page_number"))
        subjects = _coerce_str_list(item.get("subjects", item.get("Subjects")))
        signatures = _coerce_str_list(item.get("signatures"))
        doctype = _coerce_str(item.get("doctype"))
        lawnumber = _coerce_str(item.get("lawnumber"))
        raw_date = _coerce_str(item.get("date"))
        parsed_date = _parse_iso_datetime(raw_date)
        rel_path = _choose_path(item, filename)

        new_chunks.append(text if text is not None else "")
        new_page_numbers.append(page_number)
        new_paths.append(rel_path)

        new_filenames.append(filename)
        new_subjects_list.append(subjects)
        new_signatures_list.append(signatures)
        new_doctypes.append(doctype)
        new_lawnumbers.append(lawnumber)
        new_dates.append(raw_date)
        new_dates_parsed.append(parsed_date)

        # no author in legal schema; keep compatibility list aligned
        new_authors.append("")

    # In-place mutation to preserve object identity
    chunks.clear()
    chunks.extend(new_chunks)

    page_numbers.clear()
    page_numbers.extend(new_page_numbers)

    paths.clear()
    paths.extend(new_paths)

    filenames.clear()
    filenames.extend(new_filenames)

    subjects_list.clear()
    subjects_list.extend(new_subjects_list)

    signatures_list.clear()
    signatures_list.extend(new_signatures_list)

    doctypes.clear()
    doctypes.extend(new_doctypes)

    lawnumbers.clear()
    lawnumbers.extend(new_lawnumbers)

    dates.clear()
    dates.extend(new_dates)

    dates_parsed.clear()
    dates_parsed.extend(new_dates_parsed)

    authors.clear()
    authors.extend(new_authors)

    DATA_VERSION += 1


# -------------------------------------------------------------------
# Compatibility alias: many modules still call them "pages/chunks"
# -------------------------------------------------------------------
def load_pages():
    return load_chunks()


# -------------------------------------------------------------------
# Summaries
# -------------------------------------------------------------------
def compute_documents_summary():
    """
    Returns:
      {
        "total_documents": int,
        "total_pages": int,
        "documents": [
          {
            "filename": str,
            "doctype": str,
            "lawnumber": str,
            "date": str,
            "pages": int
          }
        ],
        "data_version": int
      }

    Pages are counted as number of unique non-null page_number values per file.
    If page numbers are all missing for a file, we fall back to counting rows.
    """
    pages_by_filename = defaultdict(set)
    rows_by_filename = defaultdict(int)
    first_doctype = {}
    first_lawnumber = {}
    first_date = {}

    for i, fname in enumerate(filenames):
        fname = (fname or "").strip()
        if not fname:
            continue

        rows_by_filename[fname] += 1

        if fname not in first_doctype:
            first_doctype[fname] = (doctypes[i] or "").strip()
        if fname not in first_lawnumber:
            first_lawnumber[fname] = (lawnumbers[i] or "").strip()
        if fname not in first_date:
            first_date[fname] = (dates[i] or "").strip()

        p = page_numbers[i] if i < len(page_numbers) else None
        if p is not None:
            pages_by_filename[fname].add(str(p))

    documents = []
    total_pages = 0

    for fname in sorted(rows_by_filename.keys()):
        page_count = len(pages_by_filename[fname]) if pages_by_filename[fname] else rows_by_filename[fname]
        total_pages += page_count

        documents.append({
            "filename": fname,
            "doctype": first_doctype.get(fname, ""),
            "lawnumber": first_lawnumber.get(fname, ""),
            "date": first_date.get(fname, ""),
            "pages": page_count,
        })

    return {
        "total_documents": len(documents),
        "total_pages": total_pages,
        "documents": documents,
        "data_version": DATA_VERSION,
    }


def compute_books_summary():
    """
    Backward-compatible wrapper so old routes do not explode immediately.
    """
    docs = compute_documents_summary()
    return {
        "total_books": docs["total_documents"],
        "total_pages": docs["total_pages"],
        "books": [
            {
                "book_name": d["filename"],
                "author": "",
                "category": d["doctype"],
                "pages": d["pages"],
            }
            for d in docs["documents"]
        ],
        "data_version": docs["data_version"],
    }


# -------------------------------------------------------------------
# Optional metadata update helpers
# -------------------------------------------------------------------
def _atomic_write_pickle(path: Path, data_obj):
    """
    Atomic write: write temp then replace.
    Works on Windows via os.replace.
    """
    path = Path(path)
    tmp_dir = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=str(tmp_dir))
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(data_obj, f)
        os.replace(tmp_name, str(path))
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


def update_document_metadata(
    filename: str,
    new_doctype=None,
    new_lawnumber=None,
    new_date=None,
    new_subjects=None,
    new_signatures=None,
    new_path=None,
):
    """
    Update metadata for all rows belonging to one filename inside the main pickle.
    This is optional, but useful if you later keep an admin metadata editor.

    Fields updated only when explicitly provided.
    """
    global DATA_VERSION

    target = _coerce_str(filename)
    if not target:
        raise ValueError("filename is required")

    pickle_path = _chunks_pickle_path()
    if not pickle_path.exists():
        raise FileNotFoundError(f"Pickle not found: {pickle_path}")

    with open(pickle_path, "rb") as f:
        data = pickle.load(f) or []

    changed = 0
    for item in data:
        item_filename = _coerce_str(item.get("filename"))
        if item_filename != target:
            continue

        if new_doctype is not None:
            item["doctype"] = _coerce_str(new_doctype)
        if new_lawnumber is not None:
            item["lawnumber"] = _coerce_str(new_lawnumber)
        if new_date is not None:
            item["date"] = _coerce_str(new_date)
        if new_subjects is not None:
            item["subjects"] = _coerce_str_list(new_subjects)
        if new_signatures is not None:
            item["signatures"] = _coerce_str_list(new_signatures)
        if new_path is not None:
            item["path"] = _normalize_rel_path(new_path)

        changed += 1

    if changed == 0:
        raise ValueError("filename not found")

    _atomic_write_pickle(pickle_path, data)

    # simplest + safest: full reload so all aligned arrays stay correct
    load_chunks()

    return {
        "ok": True,
        "updated_rows": changed,
        "data_version": DATA_VERSION,
    }


def update_book_metadata(book_name: str, new_author: str = None, new_category: str = None):
    """
    Backward-compatible wrapper.

    Old code used:
      - book_name
      - new_author
      - new_category

    Here:
      - book_name maps to filename
      - new_category maps to doctype
      - new_author is ignored because the legal schema has no author field
    """
    return update_document_metadata(
        filename=book_name,
        new_doctype=new_category,
    )


# -------------------------------------------------------------------
# Semantic-search helper paths
# These remain essentially unchanged.
# -------------------------------------------------------------------
def embeddings_dir() -> Path:
    return data_dir() / "embeddings"


def semantic_chunks_pickle_path() -> Path:
    return data_dir() / "chunks_tobe_embedded.pickle"


def semantic_chunk_page_mapping_pickle_path() -> Path:
    return data_dir() / "mapping_chunks_tobe_embedded_to_pages.pickle"


def _first_existing_path(candidates, label: str = "file") -> Path:
    for p in candidates:
        pp = Path(p)
        if pp.exists():
            return pp
    tried = "\n".join(str(Path(p)) for p in candidates)
    raise FileNotFoundError(f"Missing {label}. Tried:\n{tried}")


def semantic_embeddings_pickle_paths() -> dict:
    emb = embeddings_dir()

    bge3 = _first_existing_path(
        [
            emb / "embeddings_bge3_FULL.pickle",
            emb / "embeddings_bge3.pickle",
        ],
        label="BGE3 embeddings pickle",
    )

    e5 = _first_existing_path(
        [
            emb / "embeddings_e5_FULL.pickle",
            emb / "embeddings_e5.pickle",
        ],
        label="E5 embeddings pickle",
    )

    jinav3 = _first_existing_path(
        [
            emb / "embeddings_jinav3_FULL.pickle",
            emb / "embeddings_jina_FULL.pickle",
            emb / "embeddings_jina.pickle",
        ],
        label="Jina embeddings pickle",
    )

    return {
        "bge3": bge3,
        "e5": e5,
        "jinav3": jinav3,
    }


def semantic_embeddings_pickle_paths_optional() -> dict:
    emb = embeddings_dir()

    e5 = _first_existing_path(
        [
            emb / "embeddings_e5_FULL.pickle",
            emb / "embeddings_e5.pickle",
        ],
        label="E5 embeddings pickle",
    )

    jinav3 = _first_existing_path(
        [
            emb / "embeddings_jinav3_FULL.pickle",
            emb / "embeddings_jina_FULL.pickle",
            emb / "embeddings_jina.pickle",
        ],
        label="Jina embeddings pickle",
    )

    bge3 = None
    for p in [
        emb / "embeddings_bge3_FULL.pickle",
        emb / "embeddings_bge3.pickle",
        emb / "embeddings_bge3_10k.pickle",
    ]:
        if Path(p).exists():
            bge3 = Path(p)
            break

    return {
        "bge3": bge3,
        "e5": e5,
        "jinav3": jinav3,
    }