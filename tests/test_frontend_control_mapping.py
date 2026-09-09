"""
tests/test_frontend_control_mapping.py

Phase 5, item 1: guards docs/frontend-control-mapping.md's "Payload
contract" table against silently drifting from the actual `ControlType`
schema (app/core/config/models.py) -- same "explicit table, not implicit
convention" principle the config schema's own
`DEFAULT_CONTROL`/`ALLOWED_CONTROLS` tables already follow, applied to
the prose doc too.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.core.config.models import ALLOWED_CONTROLS, ControlType

_DOC_PATH = Path(__file__).parent.parent / "docs" / "frontend-control-mapping.md"


def _payload_contract_section() -> str:
    text = _DOC_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"## Payload contract.*?\n(.*?)\n## ", text, flags=re.DOTALL
    )
    assert match, "docs/frontend-control-mapping.md's 'Payload contract' section not found"
    return match.group(1)


def _controls_documented_in_payload_table() -> set[str]:
    """Every backtick-quoted control name appearing in the payload
    contract table's first column (which may list more than one control
    per row, e.g. '`dropdown` / `radio`')."""
    section = _payload_contract_section()
    table_lines = [line for line in section.splitlines() if line.startswith("| `")]
    controls: set[str] = set()
    for line in table_lines:
        first_cell = line.split("|")[1]
        controls |= set(re.findall(r"`(\w+)`", first_cell))
    return controls


def test_doc_file_exists():
    assert _DOC_PATH.exists(), "docs/frontend-control-mapping.md is missing"


def test_every_control_type_is_documented_in_payload_table():
    documented = _controls_documented_in_payload_table()
    all_controls = set(get_args(ControlType))
    missing = all_controls - documented
    assert not missing, f"ControlType values missing from the payload contract table: {sorted(missing)}"


def test_payload_table_does_not_document_a_nonexistent_control():
    documented = _controls_documented_in_payload_table()
    all_controls = set(get_args(ControlType))
    extra = documented - all_controls
    assert not extra, f"payload table lists control(s) not in ControlType: {sorted(extra)}"


def test_every_allowed_control_is_documented():
    """Belt-and-suspenders: every control name that ever appears as an
    alternate (not just default) in ALLOWED_CONTROLS must also be
    documented, not just the defaults."""
    documented = _controls_documented_in_payload_table()
    every_allowed_control: set[str] = set()
    for controls in ALLOWED_CONTROLS.values():
        every_allowed_control |= controls
    missing = every_allowed_control - documented
    assert not missing, f"controls used in ALLOWED_CONTROLS but undocumented: {sorted(missing)}"
