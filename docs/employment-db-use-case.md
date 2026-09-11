# Public-employment database use case

This is a second custom project under `app/custom/employment/`. It models an
`Emploi Public` search platform whose data is stored in normalized SQLite
tables rather than JSON files or PDFs.

## Database shape

The demo schema contains `organizations`, `locations`, `jobs`, and
`job_skills` tables. `db_raw_loader.py` joins the first three and aggregates
skills into the generic record shape:

```python
{"id": "emploi-001", "text": "...", "metadata": {...}}
```

Only this adapter knows the table names and joins. The generic ingestion,
filtering, ranking, pagination, and HTTP layers stay unchanged.

## Run the demo

From the repository root:

```bash
python scripts/seed_employment_db.py
python run_employment.py
```

The API runs on port `5001` by default. Set `EMPLOYMENT_DB_PATH` to use a
different SQLite file. The default demo is lexical-only, so it starts without
downloading a sentence-transformer model.

Example request:

```json
{
  "lexical": {"first_of": ["informatique"]},
  "filters": {
    "region": "Rabat-Salé-Kénitra",
    "skills": ["Python"],
    "salary_min": {"min": 10000},
    "remote": true,
    "status": "Ouvert"
  }
}
```

The config exposes equality filters for organization, ministry, location,
contract, education, grade, remote work, and status; contains filters for
title and skills; and range filters for dates and salary. `GET /api/config`
describes the controls and `GET /api/facets` derives available values from
the loaded database rows.

## Database boundary

This pilot loads all job rows once at startup and then uses the existing
in-memory generic engine. It proves that normalized relational data works
with the current factory and API contract. It is not query push-down: a
future large-corpus version could replace this adapter with paged or
database-backed retrieval without changing the YAML/UI contract.
