"""Heuristic metadata extraction for selectable-text Bulletin Officiel pages.

The PDF corpus is page-indexed, while one issue can contain several legal
acts.  This module therefore extracts conservative, normalized candidates
from a page and leaves the caller responsible for carrying act context across
continuation pages.  Values are deliberately kept in the vocabulary already
used by the legal filters (``dahir``, ``decret``, ``arrete``, ``loi``).

This is not an OCR or an authoritative legal-classification engine.  It is a
deterministic first pass for native/selectable text.  A metadata sidecar can
still override any value at ingestion time.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TATWEEL = "ـ"

_MONTHS: dict[str, int] = {
    "يناير": 1,
    "فبراير": 2,
    "مارس": 3,
    "أبريل": 4,
    "ابريل": 4,
    "ماي": 5,
    "مايو": 5,
    "يونيو": 6,
    "يوليو": 7,
    "يوليوز": 7,
    "غشت": 8,
    "أغسطس": 8,
    "اغسطس": 8,
    "شتنبر": 9,
    "سبتمبر": 9,
    "أكتوبر": 10,
    "اكتوبر": 10,
    "نونبر": 11,
    "نوفمبر": 11,
    "دجنبر": 12,
    "ديسمبر": 12,
}

_MONTH_PATTERN = "|".join(sorted((re.escape(name) for name in _MONTHS), key=len, reverse=True))

_DATE_PATTERNS = (
    re.compile(rf"(?P<day>\d{{1,2}})[\s()\-]*(?P<month>{_MONTH_PATTERN})[\s()\-]*(?P<year>\d{{4}})"),
    re.compile(rf"(?P<year>\d{{4}})[\s()\-]*(?P<month>{_MONTH_PATTERN})[\s()\-]*(?P<day>\d{{1,2}})"),
)

_ISSUE_PATTERN = re.compile(r"(?:^|[_\s])BO[_\s-]*(?P<number>\d+)(?P<bis>-bis)?", re.IGNORECASE)
_LAW_NUMBER_PATTERN = re.compile(r"(?<!\d)(?P<number>\d+\.\d+(?:\.\d+)?)(?!\d)")

_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("ظهير", "dahir"),
    ("مرسوم", "decret"),
    ("قرار", "arrete"),
    ("قانون", "loi"),
)

_LEGAL_MARKER_RULES: tuple[tuple[str, str], ...] = (
    (r"ظهير", "dahir"),
    (r"مرسوم", "decret"),
    (r"قرار\s+(?:لل|رقم)|قرر\s+ما\s+يلي", "arrete"),
    (r"قانون\s+(?:رقم|تنظيمي|المالية)|بمثابة\s+قانون", "loi"),
)

# Subject values are intentionally stable, ASCII identifiers suitable for
# facets.  The keys are normalized Arabic fragments found in the corpus.
_SUBJECT_RULES: tuple[tuple[str, str], ...] = (
    ("الطوارئ الصحية", "public_health"),
    ("الصحة", "public_health"),
    ("أمراض", "public_health"),
    ("التربية", "education"),
    ("التعليم", "education"),
    ("الشهادات", "education"),
    ("الانتخابات", "elections"),
    ("اللوائح الانتخابية", "elections"),
    ("المالية", "finance"),
    ("الميزانية", "finance"),
    ("الاستيراد", "finance"),
    ("الضريبة", "finance"),
    ("الضرائب", "finance"),
    ("الأجراء", "labor"),
    ("المستخدمين", "labor"),
    ("الشغل", "labor"),
    ("النقل", "transport"),
    ("اللوجيستيك", "transport"),
    ("الكهرباء", "energy_water"),
    ("الماء", "energy_water"),
    ("الفلاحة", "agriculture"),
    ("الزراعة", "agriculture"),
)


def normalize_arabic_text(value: str) -> str:
    """Normalize common PDF text noise without transliterating Arabic."""
    value = unicodedata.normalize("NFKC", value or "").translate(_ARABIC_DIGITS)
    value = value.replace(_TATWEEL, "")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _date_from_match(match: re.Match[str]) -> str | None:
    try:
        day = int(match.group("day"))
        month = _MONTHS[match.group("month")]
        year = int(match.group("year"))
        return date(year, month, day).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def extract_dates(text: str) -> list[str]:
    """Return Gregorian dates written with Arabic month names, in order."""
    normalized = normalize_arabic_text(text)
    matches: list[tuple[int, str]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(normalized):
            parsed = _date_from_match(match)
            if parsed:
                matches.append((match.start(), parsed))
    return [value for _, value in sorted(matches)]


def _extract_publication_date(text: str, expected_issue_number: str | None = None) -> str | None:
    normalized = normalize_arabic_text(text)
    header_markers = [match.start() for match in re.finditer("الجريدة الرسمية", normalized)]
    issue_digits = re.sub(r"\D", "", expected_issue_number or "")
    for header_marker in reversed(header_markers):
        # Native PDF extraction normally places the header date immediately
        # after the newspaper title.  Body text can mention the newspaper
        # later, so only accept an after-marker date on this first pass.
        after_window = normalized[header_marker : header_marker + 280]
        if issue_digits and issue_digits not in after_window[:100]:
            continue
        dates = extract_dates(after_window)
        if dates:
            return dates[0]

    # Some producers place the date before the title.  Use the closest date
    # before a marker only after the normal after-marker form was exhausted.
    for header_marker in reversed(header_markers):
        before_window = normalized[max(0, header_marker - 220) : header_marker]
        dates = extract_dates(before_window)
        if dates:
            return dates[-1]

    # The issue header is normally near the beginning of a page.  Looking
    # only at the first 1,200 chars avoids selecting a later body date.
    dates = extract_dates(normalized[:1200])
    return dates[0] if dates else None


def _extract_promulgation_date(text: str) -> str | None:
    normalized = normalize_arabic_text(text)
    for marker in re.finditer(r"حرر|حررت", normalized):
        dates = extract_dates(normalized[marker.start() : marker.start() + 700])
        if dates:
            return dates[0]

    # In many BO headings the act date precedes ``صادر في``.  Only accept
    # that form when a Gregorian month date is close to the marker; this
    # avoids treating dates from a referenced law as the current act date.
    for marker in re.finditer(r"صدر في|صادر في", normalized[:1200]):
        dates = extract_dates(normalized[max(0, marker.start() - 180) : marker.start()])
        if dates:
            return dates[-1]
    return None


def _extract_law_number(text: str) -> str | None:
    normalized = normalize_arabic_text(text)
    # Legal numbers normally occur near a document-type marker.  Restricting
    # the scan prevents article numbers and years in body text from becoming
    # the act number.
    head = normalized[:1800]
    markers = [
        match
        for pattern, _ in _LEGAL_MARKER_RULES
        for match in re.finditer(pattern, head)
    ]
    if markers:
        marker = min(markers, key=lambda match: match.start())
        window = head[max(0, marker.start() - 160) : marker.start() + 320]
    else:
        window = head
    match = _LAW_NUMBER_PATTERN.search(window)
    return match.group("number") if match else None


def _extract_document_type(text: str, fallback: str = "bulletin_officiel") -> str:
    normalized = normalize_arabic_text(text[:1800])
    matches = [
        (match.start(), canonical)
        for pattern, canonical in _LEGAL_MARKER_RULES
        for match in re.finditer(pattern, normalized)
    ]
    if matches:
        return min(matches, key=lambda item: item[0])[1]
    return fallback


def _extract_signature(text: str) -> str | None:
    normalized = normalize_arabic_text(text)
    signature_lines: list[str] = []
    for raw_line in text.splitlines():
        line = normalize_arabic_text(raw_line)
        clean = line.strip(" :؛،,.")
        if re.search(r"الإمضاء|الامضاء|وقعه بالعطف", clean):
            value = re.sub(r"^.*?(?:الإمضاء|الامضاء|وقعه بالعطف)\s*[:：]?\s*", "", clean)
            if value and value != clean:
                signature_lines.append(value)
    if signature_lines:
        return "; ".join(dict.fromkeys(signature_lines))
    if "رئيس الحكومة" in normalized:
        return "رئيس الحكومة"
    if "الملك" in normalized or "محمد بن الحسن" in normalized:
        return "الملك"
    return None


def _extract_subjects(text: str) -> list[str]:
    normalized = normalize_arabic_text(text[:1800])
    subjects: list[str] = []
    for phrase, subject in _SUBJECT_RULES:
        if normalize_arabic_text(phrase) in normalized and subject not in subjects:
            subjects.append(subject)
    return subjects


def _extract_title(text: str) -> str | None:
    lines = [
        normalize_arabic_text(raw_line).strip(" :؛،,.")
        for raw_line in text.splitlines()
        if normalize_arabic_text(raw_line).strip()
    ]
    for index, line in enumerate(lines[:20]):
        if "الجريدة الرسمية" in line:
            continue
        if any(label in line for label, _ in _TYPE_RULES) and len(line) >= 12:
            return line[:300]
        if "بتحديد" in line or "يتعلق" in line or "بإعلان" in line:
            return line[:300]
    return None


def extract_legal_metadata(
    text: str,
    file_name: str | Path,
    *,
    fallback_document_type: str = "bulletin_officiel",
) -> dict[str, Any]:
    """Extract filterable metadata from one selectable-text page."""
    name = Path(file_name).name
    normalized = normalize_arabic_text(text)
    issue_match = _ISSUE_PATTERN.search(name)
    issue_number = issue_match.group("number") if issue_match else None
    if issue_match and issue_match.group("bis"):
        issue_number = f"{issue_number}-bis"

    subjects = _extract_subjects(normalized)
    metadata: dict[str, Any] = {
        "issue_number": issue_number,
        "publication_date": _extract_publication_date(normalized, issue_number),
        "promulgation_date": _extract_promulgation_date(normalized),
        "document_type": _extract_document_type(normalized, fallback_document_type),
        "law_number": _extract_law_number(normalized),
        "signatures": _extract_signature(text),
        "subjects": subjects or None,
        "mandatory_keywords": " ".join(subjects) or None,
        "title": _extract_title(text),
    }
    return {key: value for key, value in metadata.items() if value is not None}
