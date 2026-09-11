"""Pilot tests for the normalized public-employment database use case."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.api.http import create_http_app
from app.core.config.loader import load_use_case_config
from app.custom.employment.bootstrap import build_search_engine
from app.custom.employment.db_raw_loader import load_raw_records_from_db


_SEED_SQL = Path("data/employment/employment_seed.sql")
_CONFIG = Path("app/custom/employment/config.yaml")


@pytest.fixture()
def employment_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "employment.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(_SEED_SQL.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    return db_path


@pytest.fixture()
def client(employment_db: Path):
    engine = build_search_engine(db_path=employment_db)
    app = create_http_app(engine)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_employment_config_validates_and_declares_different_filter_kinds():
    config = load_use_case_config(_CONFIG)
    assert config.search.semantic.enabled is False
    assert config.filters["skills"].operation == "contains"
    assert config.filters["publication_date"].operation == "range"
    assert config.filters["remote"].type.value == "bool"
    assert config.frontend.filters["remote"].control == "toggle"


def test_normalized_tables_are_joined_into_generic_records(employment_db: Path):
    records = load_raw_records_from_db(employment_db)
    assert len(records) == 6
    first = next(record for record in records if record["id"] == "emploi-001")
    assert first["metadata"]["organization"] == "Agence Nationale du Digital"
    assert first["metadata"]["region"] == "Rabat-Salé-Kénitra"
    assert first["metadata"]["skills"] == ["Cloud", "Python", "SQL"]
    assert "pipelines de données" in first["text"]


def test_database_engine_filters_by_region_skill_salary_and_remote(client):
    response = client.post(
        "/api/search",
        json={
            "lexical": {"first_of": ["informatique"]},
            "filters": {
                "region": "Rabat-Salé-Kénitra",
                "skills": ["Python"],
                "salary_min": {"min": 10000},
                "remote": True,
                "status": "Ouvert",
            },
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["total_hits"] == 1
    assert body["hits"][0]["id"] == "emploi-001"


def test_database_engine_exposes_config_and_facets(client):
    config = client.get("/api/config").get_json()
    assert config["branding"]["title"] == "Emploi Public"
    assert config["search"] == {"lexical": True, "semantic": False, "semantic_text": False}
    assert {field["name"] for field in config["filters"]} == {
        "title", "organization", "ministry", "region", "city", "contract_type",
        "employment_type", "education_level", "grade", "skills", "publication_date",
        "deadline", "salary_min", "salary_max", "remote", "status",
    }

    facets = client.get("/api/facets").get_json()["filters"]
    assert facets["salary_min"]["min"] == 6500
    assert facets["salary_max"]["max"] == 22000
    assert {entry["value"] for entry in facets["region"]["values"]} == {
        "Rabat-Salé-Kénitra", "Casablanca-Settat", "Fès-Meknès"
    }
    assert {entry["value"] for entry in facets["skills"]["values"]} >= {"Python", "SQL"}


def test_missing_database_fails_with_actionable_message(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="employment database not found"):
        load_raw_records_from_db(tmp_path / "missing.db")
