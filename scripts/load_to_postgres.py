"""Load the audited job-market snapshot into the PostgreSQL reporting model.

This loader intentionally works with the existing, frozen CSV snapshot. It validates
both files before touching the database. Rebuilding tables requires --rebuild.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = ROOT / "data" / "processed" / "job_postings_clean.csv"
SKILLS_FILE = ROOT / "data" / "processed" / "job_skills_bridge.csv"
SCHEMA_FILE = ROOT / "sql" / "schema.sql"

# Expectations for the published snapshot, not for a future live collection.
EXPECTED_JOBS = 5_460
EXPECTED_JOB_SKILLS = 13_122
EXPECTED_SKILLS = 44
EXPECTED_SALARIES = 92
EXPECTED_RECENT = 3_506
EXPECTED_EARLIER = 382
EXPECTED_PROXY_DATED = 1_572

FACT_COLUMNS = (
    "job_id", "role_key", "company_key", "location_key", "date_key",
    "source", "source_family", "source_provider", "title", "description",
    "work_mode", "experience_min_years", "experience_max_years", "experience_band",
    "salary_min_source", "salary_max_source", "salary_min", "salary_max",
    "salary_midpoint", "salary_is_predicted", "has_salary_source",
    "salary_analysis_eligible", "salary_normalization_status", "salary_text_evidence",
    "skill_count", "has_extracted_skill", "is_posting_date_observed",
    "is_recent_90d", "is_complete_week", "contract_type", "contract_time",
    "redirect_url",
)

REQUIRED_JOB_COLUMNS = {
    "job_id", "source", "source_family", "source_provider", "title",
    "company_name", "location_name", "city", "state", "location_scope",
    "role_family", "work_mode", "description", "posted_date",
    "is_posting_date_observed", "is_recent_90d", "is_complete_week",
    "experience_min_years", "experience_max_years", "experience_band",
    "salary_min_source", "salary_max_source", "salary_min", "salary_max",
    "salary_midpoint", "salary_is_predicted", "has_salary_source",
    "salary_analysis_eligible", "salary_normalization_status",
    "salary_text_evidence", "skill_count", "has_extracted_skill",
    "contract_type", "contract_time", "redirect_url",
}


def config(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not str(value).strip():
        raise RuntimeError(f"Missing PostgreSQL setting: {name}")
    return str(value)


def connect():
    return psycopg2.connect(
        host=config("PGHOST", "localhost"),
        port=config("PGPORT", "5432"),
        dbname=config("PGDATABASE", "job_market"),
        user=config("PGUSER", "postgres"),
        password=config("PGPASSWORD"),
    )


def nullable(value: Any) -> Any:
    """Convert pandas missing values and NumPy scalars to DB-compatible types."""
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def boolean(value: Any) -> bool:
    """Parse a stored CSV boolean without treating unexpected text as False."""
    if pd.isna(value):
        raise ValueError("Required boolean value is missing")
    if isinstance(value, (bool, int)):
        if value in (True, 1):
            return True
        if value in (False, 0):
            return False
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "1.0", "yes"}:
        return True
    if normalized in {"false", "0", "0.0", "no"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def optional_boolean(value: Any) -> bool | None:
    return None if pd.isna(value) else boolean(value)


def label(value: Any, fallback: str) -> str:
    if pd.isna(value) or not str(value).strip():
        return fallback
    return str(value).strip()


def verify_snapshot(jobs: pd.DataFrame, skills: pd.DataFrame) -> None:
    """Check that the source snapshot is complete and internally consistent."""
    missing_jobs = sorted(REQUIRED_JOB_COLUMNS - set(jobs.columns))
    missing_skills = sorted({"job_id", "skill", "skill_category"} - set(skills.columns))
    if missing_jobs or missing_skills:
        raise ValueError(
            f"Missing columns: jobs={missing_jobs or 'none'}; "
            f"job_skills={missing_skills or 'none'}"
        )

    for name, actual, expected in (
        ("jobs", len(jobs), EXPECTED_JOBS),
        ("job-skill links", len(skills), EXPECTED_JOB_SKILLS),
        ("unique skills", skills["skill"].nunique(), EXPECTED_SKILLS),
    ):
        if actual != expected:
            raise ValueError(f"Expected {expected:,} {name}, found {actual:,}")

    if jobs["job_id"].isna().any() or jobs["job_id"].duplicated().any():
        raise ValueError("job_id is missing or repeated in the job snapshot")
    if skills[["job_id", "skill", "skill_category"]].isna().any().any():
        raise ValueError("The job-skill bridge contains missing keys or categories")
    if skills.duplicated(["job_id", "skill"]).any():
        raise ValueError("The job-skill bridge contains duplicate job/skill pairs")
    if not set(skills["job_id"]).issubset(set(jobs["job_id"])):
        raise ValueError("The job-skill bridge references jobs absent from the snapshot")
    if skills.groupby("skill")["skill_category"].nunique().gt(1).any():
        raise ValueError("Some skills are assigned to multiple categories")

    dates = pd.to_datetime(jobs["posted_date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("One or more postings have an invalid reporting date")

    observed = jobs["is_posting_date_observed"].map(boolean)
    recent = jobs["is_recent_90d"].map(boolean)
    complete_week = jobs["is_complete_week"].map(boolean)
    if (recent & ~observed).any() or (complete_week & ~observed).any():
        raise ValueError("Recent/complete-week postings require an observed posting date")

    period_counts = {
        "recent": int((observed & recent).sum()),
        "earlier": int((observed & ~recent).sum()),
        "proxy dated": int((~observed).sum()),
    }
    expected_periods = {
        "recent": EXPECTED_RECENT,
        "earlier": EXPECTED_EARLIER,
        "proxy dated": EXPECTED_PROXY_DATED,
    }
    if period_counts != expected_periods:
        raise ValueError(f"Posting-date counts differ: {period_counts}")

    skill_count = pd.to_numeric(jobs["skill_count"], errors="coerce")
    has_skill = jobs["has_extracted_skill"].map(boolean)
    actual_skill_counts = skills.groupby("job_id").size().reindex(jobs["job_id"], fill_value=0)
    if (
        skill_count.isna().any()
        or (skill_count < 0).any()
        or (skill_count != actual_skill_counts.to_numpy()).any()
        or (has_skill != (skill_count > 0)).any()
    ):
        raise ValueError("Job skill counts disagree with the job-skill bridge")

    salary_eligible = jobs["salary_analysis_eligible"].map(boolean)
    if int(salary_eligible.sum()) != EXPECTED_SALARIES:
        raise ValueError("The salary-analysis sample count has changed")
    salaries = jobs.loc[
        salary_eligible, ["salary_min", "salary_max", "salary_midpoint"]
    ].apply(pd.to_numeric, errors="coerce")
    if (
        salaries.isna().any().any()
        or (salaries <= 0).any().any()
        or (salaries["salary_max"] < salaries["salary_min"]).any()
        or (salaries["salary_midpoint"] < salaries["salary_min"]).any()
        or (salaries["salary_midpoint"] > salaries["salary_max"]).any()
    ):
        raise ValueError("Salary-analysis jobs contain invalid amounts or midpoints")

    print("Snapshot validated:")
    print(f"  Jobs:             {len(jobs):,}")
    print(f"  Job-skill links:  {len(skills):,}")
    print(f"  Unique skills:    {skills['skill'].nunique():,}")
    print(f"  Salary sample:    {int(salary_eligible.sum()):,}")
    print(
        "  Posting dates:   "
        f"{period_counts['recent']:,} recent, "
        f"{period_counts['earlier']:,} earlier, "
        f"{period_counts['proxy dated']:,} proxy-dated"
    )


def rebuild_schema(cur) -> None:
    # Executed only with --rebuild, inside a single transaction.
    cur.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


def insert_rows(cur, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        execute_values(cur, sql, rows, page_size=1_000)


def load_dimensions(cur, jobs: pd.DataFrame, skills: pd.DataFrame) -> None:
    roles = sorted({label(value, "Other Analyst") for value in jobs["role_family"]})
    insert_rows(
        cur,
        "INSERT INTO job_market.dim_role (role_family) VALUES %s",
        [(role,) for role in roles],
    )

    companies = sorted({label(value, "Unknown Company") for value in jobs["company_name"]})
    insert_rows(
        cur,
        "INSERT INTO job_market.dim_company (company_name) VALUES %s",
        [(company,) for company in companies],
    )

    locations = sorted({
        (
            label(row.city, "Unknown"),
            label(row.state, "Unknown"),
            label(row.location_name, "Unknown"),
            label(row.location_scope, "Unknown"),
        )
        for row in jobs[["city", "state", "location_name", "location_scope"]].itertuples(index=False)
    })
    insert_rows(
        cur,
        """INSERT INTO job_market.dim_location
           (city, state, location_name, location_scope) VALUES %s""",
        locations,
    )

    posted_dates = pd.to_datetime(jobs["posted_date"])
    unique_dates = sorted(set(posted_dates.dt.date))
    date_rows = []
    for day in unique_dates:
        timestamp = pd.Timestamp(day)
        week_start = (timestamp - pd.Timedelta(days=timestamp.day_of_week)).date()
        date_rows.append((
            day, timestamp.year, timestamp.month, timestamp.month_name(),
            timestamp.strftime("%Y-%m"), week_start, timestamp.day_of_week,
            timestamp.day_name(),
        ))
    insert_rows(
        cur,
        """INSERT INTO job_market.dim_date
           (date_key, calendar_year, calendar_month, month_name,
            year_month, week_start, day_of_week, day_name) VALUES %s""",
        date_rows,
    )

    skill_dim = skills[["skill", "skill_category"]].drop_duplicates()
    insert_rows(
        cur,
        "INSERT INTO job_market.dim_skill (skill, skill_category) VALUES %s",
        sorted((str(row.skill), str(row.skill_category))
               for row in skill_dim.itertuples(index=False)),
    )


def key_lookup(cur, table: str, key: str, attributes: tuple[str, ...]) -> dict[tuple[str, ...], int]:
    """Read surrogate keys from a known dimension table."""
    columns = ", ".join((key, *attributes))
    # All identifiers come from fixed calls below, never user input.
    cur.execute(f"SELECT {columns} FROM job_market.{table}")
    return {
        tuple(str(value) for value in record[1:]): int(record[0])
        for record in cur.fetchall()
    }


def load_jobs(cur, jobs: pd.DataFrame) -> None:
    roles = key_lookup(cur, "dim_role", "role_key", ("role_family",))
    companies = key_lookup(cur, "dim_company", "company_key", ("company_name",))
    locations = key_lookup(
        cur, "dim_location", "location_key",
        ("city", "state", "location_name", "location_scope"),
    )

    records = []
    for job in jobs.itertuples(index=False):
        role = label(job.role_family, "Other Analyst")
        company = label(job.company_name, "Unknown Company")
        location = (
            label(job.city, "Unknown"),
            label(job.state, "Unknown"),
            label(job.location_name, "Unknown"),
            label(job.location_scope, "Unknown"),
        )
        record = {
            "job_id": str(job.job_id),
            "role_key": roles[(role,)],
            "company_key": companies[(company,)],
            "location_key": locations[location],
            "date_key": pd.Timestamp(job.posted_date).date(),
            "source": nullable(job.source),
            "source_family": nullable(job.source_family),
            "source_provider": nullable(job.source_provider),
            "title": label(job.title, "Untitled job"),
            "description": nullable(job.description),
            "work_mode": label(job.work_mode, "Not Specified"),
            "experience_min_years": nullable(job.experience_min_years),
            "experience_max_years": nullable(job.experience_max_years),
            "experience_band": label(job.experience_band, "Not Specified"),
            "salary_min_source": nullable(job.salary_min_source),
            "salary_max_source": nullable(job.salary_max_source),
            "salary_min": nullable(job.salary_min),
            "salary_max": nullable(job.salary_max),
            "salary_midpoint": nullable(job.salary_midpoint),
            "salary_is_predicted": optional_boolean(job.salary_is_predicted),
            "has_salary_source": boolean(job.has_salary_source),
            "salary_analysis_eligible": boolean(job.salary_analysis_eligible),
            "salary_normalization_status": nullable(job.salary_normalization_status),
            "salary_text_evidence": nullable(job.salary_text_evidence),
            "skill_count": int(job.skill_count),
            "has_extracted_skill": boolean(job.has_extracted_skill),
            "is_posting_date_observed": boolean(job.is_posting_date_observed),
            "is_recent_90d": boolean(job.is_recent_90d),
            "is_complete_week": boolean(job.is_complete_week),
            "contract_type": nullable(job.contract_type),
            "contract_time": nullable(job.contract_time),
            "redirect_url": nullable(job.redirect_url),
        }
        records.append(tuple(record[column] for column in FACT_COLUMNS))

    columns = ", ".join(FACT_COLUMNS)
    insert_rows(
        cur,
        f"INSERT INTO job_market.fact_jobs ({columns}) VALUES %s",
        records,
    )


def load_job_skills(cur, skills: pd.DataFrame) -> None:
    cur.execute("SELECT job_id, job_key FROM job_market.fact_jobs")
    job_ids = {str(job_id): job_key for job_id, job_key in cur.fetchall()}
    cur.execute("SELECT skill, skill_key FROM job_market.dim_skill")
    skill_ids = {str(skill): skill_key for skill, skill_key in cur.fetchall()}

    rows = [
        (job_ids[str(row.job_id)], skill_ids[str(row.skill)])
        for row in skills.itertuples(index=False)
    ]
    insert_rows(
        cur,
        "INSERT INTO job_market.bridge_job_skill (job_key, skill_key) VALUES %s",
        rows,
    )


def count(cur, statement: str) -> int:
    cur.execute(statement)
    return int(cur.fetchone()[0])


def verify_database(cur) -> None:
    checks = (
        ("jobs", "SELECT COUNT(*) FROM job_market.fact_jobs", EXPECTED_JOBS),
        ("job-skill links", "SELECT COUNT(*) FROM job_market.bridge_job_skill", EXPECTED_JOB_SKILLS),
        ("skills", "SELECT COUNT(*) FROM job_market.dim_skill", EXPECTED_SKILLS),
        ("salary sample", "SELECT COUNT(*) FROM job_market.fact_jobs WHERE salary_analysis_eligible", EXPECTED_SALARIES),
        ("recent dated jobs", "SELECT COUNT(*) FROM job_market.fact_jobs WHERE is_posting_date_observed AND is_recent_90d", EXPECTED_RECENT),
        ("earlier dated jobs", "SELECT COUNT(*) FROM job_market.fact_jobs WHERE is_posting_date_observed AND NOT is_recent_90d", EXPECTED_EARLIER),
        ("proxy-dated jobs", "SELECT COUNT(*) FROM job_market.fact_jobs WHERE NOT is_posting_date_observed", EXPECTED_PROXY_DATED),
        ("invalid date flags", """SELECT COUNT(*) FROM job_market.fact_jobs
            WHERE (is_recent_90d OR is_complete_week) AND NOT is_posting_date_observed""", 0),
        ("mismatched skill counts", """SELECT COUNT(*)
            FROM job_market.fact_jobs AS f
            LEFT JOIN (
                SELECT job_key, COUNT(*) AS links
                FROM job_market.bridge_job_skill GROUP BY job_key
            ) AS b ON b.job_key = f.job_key
            WHERE f.skill_count <> COALESCE(b.links, 0)
               OR f.has_extracted_skill <> (COALESCE(b.links, 0) > 0)""", 0),
    )
    for name, sql, expected in checks:
        actual = count(cur, sql)
        if actual != expected:
            raise RuntimeError(f"Database {name}: expected {expected:,}, found {actual:,}")
    print("PostgreSQL load verified: 5,460 jobs and 13,122 job-skill links")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Drop and reload the existing job_market reporting tables (destructive)",
    )
    args = parser.parse_args()

    for path in (JOBS_FILE, SKILLS_FILE, SCHEMA_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"Required project file not found: {path}")

    jobs = pd.read_csv(JOBS_FILE, low_memory=False)
    skills = pd.read_csv(SKILLS_FILE, low_memory=False)
    verify_snapshot(jobs, skills)

    if not args.rebuild:
        print("No database changes made. Use --rebuild to refresh the reporting tables.")
        return

    connection = connect()
    try:
        # Any failing insert or integrity check rolls back the entire rebuild.
        with connection:
            with connection.cursor() as cur:
                rebuild_schema(cur)
                load_dimensions(cur, jobs, skills)
                load_jobs(cur, jobs)
                load_job_skills(cur, skills)
                verify_database(cur)
    finally:
        connection.close()
    print("Reporting tables committed successfully.")


if __name__ == "__main__":
    main()
