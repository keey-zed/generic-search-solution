"""
tests/test_frontend_control_mapping.py

Phase 5, item 1: guards docs/frontend-control-mapping.md against
silently drifting from the actual `ControlType` schema
(app/core/config/models.py) -- the same "explicit table, not implicit
convention" principle the config schema's own
`DEFAULT_CONTROL`/`ALLOWED_CONTROLS` tables already follow, applied to
the prose doc too: if a control name is ever added, renamed, or removed
in code, this test fails until the doc is updated to match, rather than
the two silently disagreeing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.core.config.models import ALLOWED_CONTROLS, ControlType

_DOC_PATH = Path(__file__).parent.parent / "docs" / "frontend-control-mapping.md"


def _controls_documented_in_markdown_table() -> set[str]:
    """Extract every backtick-quoted control name from the first column
    of the doc's main mapping table (lines like '| `text` | ... |')."""
    text = _DOC_PATH.read_text()
    return set(re.findall(r"^\| `(\w+)` \|", text, flags=re.MULTILINE))


def test_doc_file_exists():
    assert _DOC_PATH.exists(), "docs/frontend-control-mapping.md is missing"


def test_every_control_type_is_documented():
    documented = _controls_documented_in_markdown_table()
    all_controls = set(get_args(ControlType))
    missing = all_controls - documented
    assert not missing, f"ControlType values missing from the doc's table: {sorted(missing)}"


def test_doc_does_not_document_a_nonexistent_control():
    documented = _controls_documented_in_markdown_table()
    all_controls = set(get_args(ControlType))
    extra = documented - all_controls
    assert not extra, f"doc's table lists control(s) not in ControlType: {sorted(extra)}"


def test_every_allowed_control_is_documented():
    """Belt-and-suspenders: every control name that ever appears as an
    alternate (not just default) in ALLOWED_CONTROLS must also be
    documented, not just the defaults."""
    documented = _controls_documented_in_markdown_table()
    every_allowed_control: set[str] = set()
    for controls in ALLOWED_CONTROLS.values():
        every_allowed_control |= controls
    missing = every_allowed_control - documented
    assert not missing, f"controls used in ALLOWED_CONTROLS but undocumented: {sorted(missing)}"