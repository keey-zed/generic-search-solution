"""SQLite adapter for the public-employment search example."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def load_raw_records_from_db(db_path: str | Path) -> list[dict[str, Any]]:
    """Join normalized employment tables into generic search records."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"employment database not found: {path} -- run "
            "scripts/seed_employment_db.py first or provide EMPLOYMENT_DB_PATH"
        )

    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT j.id, j.title, j.description, j.contract_type,
                   j.employment_type, j.education_level, j.grade,
                   j.salary_min, j.salary_max, j.publication_date,
                   j.deadline, j.remote, j.status,
                   o.name AS organization, o.ministry,
                   l.region, l.city
            FROM jobs AS j
            JOIN organizations AS o ON o.id = j.organization_id
            JOIN locations AS l ON l.id = j.location_id
            ORDER BY j.publication_date DESC, j.id
            """
        ).fetchall()
        skill_rows = connection.execute(
            "SELECT job_id, skill FROM job_skills ORDER BY job_id, skill"
        ).fetchall()
    finally:
        connection.close()

    skills_by_job: dict[str, list[str]] = {}
    for row in skill_rows:
        skills_by_job.setdefault(str(row["job_id"]), []).append(row["skill"])

    records: list[dict[str, Any]] = []
    for row in rows:
        job_id = str(row["id"])
        skills = skills_by_job.get(job_id, [])
        text_parts = [
            row["title"], row["description"], row["organization"],
            row["ministry"], row["region"], row["city"],
            row["education_level"], row["employment_type"], *skills,
        ]
        records.append({
            "id": job_id,
            "text": "\n".join(str(part) for part in text_parts if part),
            "metadata": {
                "title": row["title"],
                "organization": row["organization"],
                "ministry": row["ministry"],
                "region": row["region"],
                "city": row["city"],
                "contract_type": row["contract_type"],
                "employment_type": row["employment_type"],
                "education_level": row["education_level"],
                "grade": row["grade"],
                "skills": skills,
                "publication_date": row["publication_date"],
                "deadline": row["deadline"],
                "salary_min": row["salary_min"],
                "salary_max": row["salary_max"],
                "remote": bool(row["remote"]),
                "status": row["status"],
                "description": row["description"],
            },
        })
    return records
