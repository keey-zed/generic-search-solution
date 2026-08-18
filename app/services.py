import re
import threading
from datetime import datetime, timezone

from . import data_loader as dl

_ARABIC_DIACRITICS = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]')
_ALLOWED = re.compile(r'[^0-9\u0600-\u06FFa-zA-Z\s\-/\._:]')


# -------------------------------------------------------------------
# Text normalization
# -------------------------------------------------------------------
def normalize_arabic(text: str) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = text.strip()
    if not text:
        return ""

    text = _ARABIC_DIACRITICS.sub('', text)
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'[يى]', 'ي', text)
    text = re.sub(r'ة', 'ه', text)

    # Arabic-Indic digits -> Western digits
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    text = text.translate(trans)

    text = text.casefold()
    text = _ALLOWED.sub(' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _strip_leading_topic_number(s: str) -> str:
    if not s:
        return s
    return re.sub(r'^\s*\d{1,3}\s*[\.\-]\s*', '', s).strip()


# -------------------------------------------------------------------
# Generic helpers
# -------------------------------------------------------------------
def _as_clean_list(value):
    """
    Accepts:
      - None
      - single string
      - list / tuple / set
    Returns list[str] stripped, without empties.
    """
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        out = []
        for x in value:
            s = str(x).strip()
            if s:
                out.append(s)
        return out

    s = str(value).strip()
    return [s] if s else []


def _normalize_value_set(values):
    out = set()
    for v in _as_clean_list(values):
        n = normalize_arabic(v)
        if n:
            out.add(n)
    return out


def _normalize_subject_like_values(values):
    """
    For subject-style labels, keep support for stripping leading numbering.
    """
    out = set()
    for v in _as_clean_list(values):
        n1 = normalize_arabic(v)
        if n1:
            out.add(n1)
        n2 = normalize_arabic(_strip_leading_topic_number(v))
        if n2:
            out.add(n2)
    return out


def _parse_filter_date(v):
    """
    Parse date filters safely.

    Supports:
      - YYYY-MM-DD
      - full ISO datetime
      - ISO ending with Z
    Returns timezone-aware datetime or None.
    """
    if v is None:
        return None

    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    s = str(v).strip()
    if not s:
        return None

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


# -------------------------------------------------------------------
# Caches
# -------------------------------------------------------------------
_cache_version = None

_chunks_norm = None
_filename_norm = None
_subjects_norm = None       # list[set[str]]
_signatures_norm = None     # list[set[str]]
_doctypes_norm = None       # list[str]
_lawnumbers_norm = None     # list[str]
_dates_cache = None         # list[datetime|None]

_filename_index_norm = None     # dict[str, list[int]]
_doctype_index_norm = None      # dict[str, list[int]]
_lawnumber_index_norm = None    # dict[str, list[int]]

_cache_lock = threading.Lock()


def _ensure_caches():
    global _cache_version
    global _chunks_norm, _filename_norm, _subjects_norm, _signatures_norm
    global _doctypes_norm, _lawnumbers_norm, _dates_cache
    global _filename_index_norm, _doctype_index_norm, _lawnumber_index_norm

    ver = getattr(dl, "DATA_VERSION", None)
    if ver is None:
        ver = (id(dl.chunks), len(dl.chunks))

    if (
        _cache_version == ver
        and _chunks_norm is not None
        and _filename_index_norm is not None
        and _doctype_index_norm is not None
        and _lawnumber_index_norm is not None
    ):
        return

    with _cache_lock:
        ver = getattr(dl, "DATA_VERSION", None)
        if ver is None:
            ver = (id(dl.chunks), len(dl.chunks))

        if (
            _cache_version == ver
            and _chunks_norm is not None
            and _filename_index_norm is not None
            and _doctype_index_norm is not None
            and _lawnumber_index_norm is not None
        ):
            return

        _chunks_norm = [normalize_arabic(c) for c in dl.chunks]
        _filename_norm = [normalize_arabic(x) for x in getattr(dl, "filenames", [])]
        _doctypes_norm = [normalize_arabic(x) for x in getattr(dl, "doctypes", [])]
        _lawnumbers_norm = [normalize_arabic(x) for x in getattr(dl, "lawnumbers", [])]
        _dates_cache = list(getattr(dl, "dates_parsed", []))

        # subjects cache
        _subjects_norm = []
        for subs in getattr(dl, "subjects_list", []):
            sset = set()
            if subs:
                for x in subs:
                    if x is None:
                        continue
                    raw = str(x).strip()
                    if not raw:
                        continue
                    n1 = normalize_arabic(raw)
                    if n1:
                        sset.add(n1)
                    n2 = normalize_arabic(_strip_leading_topic_number(raw))
                    if n2:
                        sset.add(n2)
            _subjects_norm.append(sset)

        # signatures cache
        _signatures_norm = []
        for sigs in getattr(dl, "signatures_list", []):
            sset = set()
            if sigs:
                for x in sigs:
                    if x is None:
                        continue
                    raw = str(x).strip()
                    if not raw:
                        continue
                    n = normalize_arabic(raw)
                    if n:
                        sset.add(n)
            _signatures_norm.append(sset)

        # exact normalized indexes for dropdown-based filters
        filename_idx = {}
        for i, val in enumerate(_filename_norm):
            if not val:
                continue
            filename_idx.setdefault(val, []).append(i)

        doctype_idx = {}
        for i, val in enumerate(_doctypes_norm):
            if not val:
                continue
            doctype_idx.setdefault(val, []).append(i)

        lawnumber_idx = {}
        for i, val in enumerate(_lawnumbers_norm):
            if not val:
                continue
            lawnumber_idx.setdefault(val, []).append(i)

        _filename_index_norm = filename_idx
        _doctype_index_norm = doctype_idx
        _lawnumber_index_norm = lawnumber_idx

        _cache_version = ver


# -------------------------------------------------------------------
# Filter extraction helpers
# -------------------------------------------------------------------
def _extract_date_range(filters):
    """
    Supports any of:
      - {"date": {"from": "...", "to": "..."}}
      - {"date_from": "...", "date_to": "..."}
      - {"dateFrom": "...", "dateTo": "..."}
    """
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")

    if date_from is None and date_to is None:
        date_from = filters.get("dateFrom")
        date_to = filters.get("dateTo")

    date_obj = filters.get("date")
    if isinstance(date_obj, dict):
        if date_from is None:
            date_from = date_obj.get("from", date_obj.get("date_from", date_obj.get("start")))
        if date_to is None:
            date_to = date_obj.get("to", date_obj.get("date_to", date_obj.get("end")))

    return _parse_filter_date(date_from), _parse_filter_date(date_to)


def _intersect_with_index_map(valid, selected_values, index_map):
    """
    Given currently valid indices and selected normalized values,
    keep rows whose field matches ANY selected value exactly.
    """
    if not selected_values:
        return valid

    selected_hits = set()
    for val in selected_values:
        hits = index_map.get(val)
        if hits:
            selected_hits.update(hits)

    if not selected_hits:
        return []

    return [i for i in valid if i in selected_hits]


# -------------------------------------------------------------------
# Legal filters
# -------------------------------------------------------------------
def get_valid_indices(filters):
    """
    Supported legal filters:
      - mandatoryKeywords: list[str]          -> ALL must appear in page text
      - filename: str | list[str]             -> OR exact match on selected values
      - subjects: str | list[str]             -> OR within page subjects
      - signatures: str | list[str]           -> OR within page signatures
      - doctype: str | list[str]              -> OR exact match on selected values
      - lawnumber: str | list[str]            -> OR exact match on selected values
      - date / date_from / date_to            -> inclusive range

    Backward-compatible fallbacks:
      - topics   -> subjects
      - bookName -> filename
    """
    _ensure_caches()

    mandatory_keywords = filters.get("mandatoryKeywords", []) or []

    # new names with backward-compatible fallbacks
    filenames_filter = filters.get("filename")
    if filenames_filter is None:
        filenames_filter = filters.get("bookName")

    subjects_filter = filters.get("subjects")
    if subjects_filter is None:
        subjects_filter = filters.get("topics")

    signatures_filter = filters.get("signatures")
    doctypes_filter = filters.get("doctype")
    lawnumbers_filter = filters.get("lawnumber")

    date_from, date_to = _extract_date_range(filters)

    # Start with all rows
    valid = list(range(len(dl.chunks)))
    if not valid:
        return []

    # filename exact OR
    filename_selected = _normalize_value_set(filenames_filter)
    if filename_selected:
        valid = _intersect_with_index_map(valid, filename_selected, _filename_index_norm)
        if not valid:
            return []

    # doctype exact OR
    doctype_selected = _normalize_value_set(doctypes_filter)
    if doctype_selected:
        valid = _intersect_with_index_map(valid, doctype_selected, _doctype_index_norm)
        if not valid:
            return []

    # lawnumber exact OR
    lawnumber_selected = _normalize_value_set(lawnumbers_filter)
    if lawnumber_selected:
        valid = _intersect_with_index_map(valid, lawnumber_selected, _lawnumber_index_norm)
        if not valid:
            return []

    # mandatory keywords: ALL must appear in normalized text
    if mandatory_keywords:
        kws = [normalize_arabic(x) for x in mandatory_keywords if str(x).strip()]
        kws = [kw for kw in kws if kw]
        if kws:
            valid = [i for i in valid if all(kw in _chunks_norm[i] for kw in kws)]
            if not valid:
                return []

    # subjects: OR among selected values
    subject_selected = _normalize_subject_like_values(subjects_filter)
    if subject_selected:
        valid = [i for i in valid if (_subjects_norm[i] & subject_selected)]
        if not valid:
            return []

    # signatures: OR among selected values
    signature_selected = _normalize_value_set(signatures_filter)
    if signature_selected:
        valid = [i for i in valid if (_signatures_norm[i] & signature_selected)]
        if not valid:
            return []

    # date inclusive range
    if date_from is not None or date_to is not None:
        filtered = []
        for i in valid:
            row_dt = _dates_cache[i] if i < len(_dates_cache) else None
            if row_dt is None:
                continue
            if date_from is not None and row_dt < date_from:
                continue
            if date_to is not None and row_dt > date_to:
                continue
            filtered.append(i)

        valid = filtered
        if not valid:
            return []

    return valid


# -------------------------------------------------------------------
# Main lexical query search
# -------------------------------------------------------------------
def search_fuzzy(query, valid_indices):
    """
    Pure normalized substring search over page text.

    Supports:
      - query: str
      - query: list[str] -> OR across queries

    Always respects valid_indices.
    """
    _ensure_caches()

    def _unique_preserve_order(seq):
        out = []
        seen = set()
        for x in seq:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    valid_list = list(valid_indices)

    # Multi-query OR
    if isinstance(query, (list, tuple, set)):
        raw_list = [str(x).strip() for x in query if str(x).strip()]
        if not raw_list:
            return [], []

        expanded = []
        result_set = set()

        for raw in raw_list:
            q_norm = normalize_arabic(raw)
            if not q_norm:
                continue

            expanded.append(q_norm)

            for i in valid_list:
                if q_norm in _chunks_norm[i]:
                    result_set.add(i)

        result = sorted(result_set)
        return result, _unique_preserve_order(expanded)

    # Single query
    if not isinstance(query, str):
        return [], []

    base = query.strip()
    if not base:
        return [], []

    q_norm = normalize_arabic(base)
    if not q_norm:
        return [], []

    result = [i for i in valid_list if q_norm in _chunks_norm[i]]
    result.sort()
    return result, [q_norm]


# -------------------------------------------------------------------
# Optional helper for the future filters endpoint
# -------------------------------------------------------------------
def get_filter_options():
    """
    Convenient backend helper for a future /filters/options endpoint.
    """
    _ensure_caches()

    def _sorted_unique_str(values):
        return sorted({str(v).strip() for v in values if str(v).strip()})

    all_subjects = []
    for row in getattr(dl, "subjects_list", []):
        all_subjects.extend(row or [])

    all_signatures = []
    for row in getattr(dl, "signatures_list", []):
        all_signatures.extend(row or [])

    parsed_dates = [d for d in getattr(dl, "dates_parsed", []) if d is not None]

    return {
        "filenames": _sorted_unique_str(getattr(dl, "filenames", [])),
        "subjects": _sorted_unique_str(all_subjects),
        "signatures": _sorted_unique_str(all_signatures),
        "doctypes": _sorted_unique_str(getattr(dl, "doctypes", [])),
        "lawnumbers": _sorted_unique_str(getattr(dl, "lawnumbers", [])),
        "date_bounds": {
            "min": min(parsed_dates).isoformat().replace("+00:00", "Z") if parsed_dates else None,
            "max": max(parsed_dates).isoformat().replace("+00:00", "Z") if parsed_dates else None,
        },
    }