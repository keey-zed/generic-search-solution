"""
tests/test_phase5_definition_of_done.py

Phase 5's stated Definition of Done:

    "adding/removing/reordering a filter in the legal YAML changes the
    rendered UI with zero frontend code edits."

Scope, stated honestly: "front-end code already exists" per the roadmap
(this repo is backend-only; the actual UI lives in a separate frontend
codebase not available in this session). What this test proves is the
backend-observable equivalent, and the maximal honest proxy available
here: mutating ONLY the legal config data (loaded, mutated as a plain
dict, and re-serialized -- the real `app/custom/legal/config.yaml`
file on disk is never touched) changes what `GET /api/config` and
`GET /api/facets` return, with ZERO changes to any `.py` file anywhere in
this repo -- not `app/api/http.py`, not `app/api/orchestrator.py`, not
`app/custom/legal/bootstrap.py`. Since those two endpoints are
exactly what a real frontend would read to decide what controls to
render, in what order, with what labels/placeholders/options -- this is
the backend half of "the rendered UI changes with zero frontend code
edits" made concrete and testable without needing the frontend itself.

This reuses the exact same raw data and ingestion path as
`tests/test_custom_layer_template.py` / `tests/test_http_api.py` --
only the config dict passed through `build_search_engine()` differs
between tests, via `bootstrap.build_search_engine(config_path=...)`,
which already existed and was never modified to make this work.
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.api.http import create_http_app
from app.custom.legal.bootstrap import build_search_engine

_ORIGINAL_CONFIG_PATH = Path("app/custom/legal/config.yaml")


def _load_baseline_config_dict() -> dict[str, Any]:
    return yaml.safe_load(_ORIGINAL_CONFIG_PATH.read_text(encoding="utf-8"))


def _engine_from_config_dict(config: dict[str, Any]):
    """Serialize `config` to a temp YAML file and build a real
    SearchEngine from it -- reusing legal's own raw_loader /
    custom_filters (bootstrap.py only swaps which config.yaml is read),
    so the only thing that ever differs between calls in this file is
    config data, never Python code."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(config, f)
        temp_path = f.name
    return build_search_engine(config_path=temp_path)


def _client_for(engine):
    app = create_http_app(engine)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def baseline_config() -> dict[str, Any]:
    return _load_baseline_config_dict()


# ---------------------------------------------------------------------------
# Baseline: the real, unmodified legal config -- establishes "before" for
# the mutation tests below.
# ---------------------------------------------------------------------------


def test_baseline_legal_config_exposes_eight_filters_in_declared_order(baseline_config):
    engine = _engine_from_config_dict(baseline_config)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    assert [f["name"] for f in body["filters"]] == [
        "mandatory_keywords",
        "subjects",
        "signatures",
        "file_name",
        "document_type",
        "law_number",
        "publication_date",
        "promulgation_date",
    ]


# ---------------------------------------------------------------------------
# Adding a filter
# ---------------------------------------------------------------------------


def test_adding_a_filter_appears_in_api_config_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    mutated["filters"]["cross_reference_count"] = {
        "type": "int",
        "required": False,
        "operation": "range",
    }
    mutated["frontend"]["filters"]["cross_reference_count"] = {
        "label": "Nombre de références croisées",
        "order": 9,
    }

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    names = [f["name"] for f in body["filters"]]
    assert "cross_reference_count" in names
    assert names[-1] == "cross_reference_count"  # respects the declared order: 9

    new_filter = next(f for f in body["filters"] if f["name"] == "cross_reference_count")
    assert new_filter["type"] == "int"
    assert new_filter["operation"] == "range"
    assert new_filter["control"] is not None  # resolved to a default control automatically


def test_added_filter_also_appears_in_facets_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    mutated["filters"]["page_count"] = {"type": "int", "required": False, "operation": "range"}
    mutated["frontend"]["filters"]["page_count"] = {"label": "Nombre de pages", "order": 9}

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    facets = client.get("/api/facets").get_json()["filters"]
    assert "page_count" in facets


# ---------------------------------------------------------------------------
# Removing a filter
# ---------------------------------------------------------------------------


def test_removing_a_filter_disappears_from_api_config_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    del mutated["filters"]["subjects"]
    del mutated["frontend"]["filters"]["subjects"]
    mutated["frontend"]["result_card_fields"] = [
        f for f in mutated["frontend"]["result_card_fields"] if f != "subjects"
    ]

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    names = [f["name"] for f in body["filters"]]
    assert "subjects" not in names
    assert len(names) == 7
    assert "subjects" not in body["result_card_fields"]


def test_removed_filter_disappears_from_facets_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    del mutated["filters"]["promulgation_date"]
    del mutated["frontend"]["filters"]["promulgation_date"]

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    facets = client.get("/api/facets").get_json()["filters"]
    assert "promulgation_date" not in facets


# ---------------------------------------------------------------------------
# Reordering filters
# ---------------------------------------------------------------------------


def test_reordering_filters_changes_api_config_order_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    mutated["frontend"]["filters"]["mandatory_keywords"]["order"] = 3
    mutated["frontend"]["filters"]["subjects"]["order"] = 4
    mutated["frontend"]["filters"]["signatures"]["order"] = 5
    mutated["frontend"]["filters"]["file_name"]["order"] = 6
    mutated["frontend"]["filters"]["law_number"]["order"] = 7
    mutated["frontend"]["filters"]["document_type"]["order"] = 2
    mutated["frontend"]["filters"]["publication_date"]["order"] = 1

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    names = [f["name"] for f in body["filters"]]
    # publication_date (order: 1) now comes before document_type (order: 2).
    assert names[0] == "publication_date"
    assert names[1] == "document_type"
    assert names[2:] == ["mandatory_keywords", "subjects", "signatures", "file_name", "law_number", "promulgation_date"]


# ---------------------------------------------------------------------------
# Relabeling — the simplest possible config-only change
# ---------------------------------------------------------------------------


def test_changing_a_label_changes_api_config_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    mutated["frontend"]["filters"]["document_type"]["label"] = "Catégorie du document"

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    doctype_filter = next(f for f in body["filters"] if f["name"] == "document_type")
    assert doctype_filter["label"] == "Catégorie du document"


def test_changing_a_control_changes_api_config_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    assert mutated["frontend"]["filters"]["document_type"]["control"] == "dropdown"
    mutated["frontend"]["filters"]["document_type"]["control"] = "radio"

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    field = next(f for f in body["filters"] if f["name"] == "document_type")
    assert field["control"] == "radio"


# ---------------------------------------------------------------------------
# Branding — also config-only
# ---------------------------------------------------------------------------


def test_changing_branding_changes_api_config_with_zero_code_changes(baseline_config):
    mutated = copy.deepcopy(baseline_config)
    mutated["frontend"]["branding"]["title"] = "Nouvelle Application"

    engine = _engine_from_config_dict(mutated)
    client = _client_for(engine)
    body = client.get("/api/config").get_json()
    assert body["branding"]["title"] == "Nouvelle Application"
