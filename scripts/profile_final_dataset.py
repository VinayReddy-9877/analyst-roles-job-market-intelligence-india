"""Create a readable statistical profile from the frozen analytical CSVs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = ROOT / "data" / "processed" / "job_postings_clean.csv"
SKILLS_FILE = ROOT / "data" / "processed" / "job_skills_bridge.csv"
LOCK_FILE = ROOT / "config" / "dataset_lock.json"
REPORT_FILE = ROOT / "reports" / "final_analysis_profile.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .isin({"true", "1", "1.0", "yes", "y"})
    )


def table(frame: pd.DataFrame | pd.Series) -> str:
    return frame.to_string()


def add_section(lines: list[str], title: str, body: str) -> None:
    lines.extend(["", title, "-" * len(title), body])


def main() -> None:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    locked_jobs = lock["sha256"]["data/processed/job_postings_clean.csv"]
    locked_skills = lock["sha256"]["data/processed/job_skills_bridge.csv"]
    if (
        sha256(JOBS_FILE) != locked_jobs.upper()
        or sha256(SKILLS_FILE) != locked_skills.upper()
    ):
        raise RuntimeError("Frozen processed-file hash check failed.")

    jobs = pd.read_csv(JOBS_FILE, low_memory=False)
    skills = pd.read_csv(SKILLS_FILE, low_memory=False)
    for column in [
        "has_extracted_skill",
        "experience_explicit_flag",
        "entry_level_flag",
        "is_posting_date_observed",
        "is_recent_90d",
        "is_complete_week",
        "salary_analysis_eligible",
    ]:
        jobs[column] = as_bool(jobs[column])

    total = len(jobs)
    skill_tagged = int(jobs["has_extracted_skill"].sum())
    observed = jobs[jobs["is_posting_date_observed"]].copy()
    salary = jobs[jobs["salary_analysis_eligible"]].copy()
    observed["posted_date"] = pd.to_datetime(observed["posted_date"], errors="raise")

    lines = [
        "INDIA ANALYTICS JOB MARKET — FINAL DATA PROFILE",
        "=" * 62,
        f"Frozen dataset: {lock['dataset_freeze_date']}",
        f"Posting window: {lock['window_start_utc']} to {lock['window_end_utc']}",
        f"Final unique jobs: {total:,}",
        f"Job-skill relationships: {len(skills):,}",
        f"Unique extracted skills: {skills['skill'].nunique():,}",
        f"Jobs with at least one extracted skill: {skill_tagged:,} ({skill_tagged / total:.1%})",
        f"Jobs with explicit experience: {int(jobs['experience_explicit_flag'].sum()):,} ({jobs['experience_explicit_flag'].mean():.1%})",
        f"Observed posting dates: {len(observed):,} ({len(observed) / total:.1%})",
        f"Proxy posting dates: {total - len(observed):,} ({1 - len(observed) / total:.1%})",
        f"Salary-analysis rows: {len(salary):,} ({len(salary) / total:.1%})",
        f"Unique employers: {jobs['company_name'].nunique():,}",
        f"Unique non-placeholder cities: {jobs.loc[~jobs['city'].isin(['City Not Specified', 'India']), 'city'].nunique():,}",
    ]

    source = jobs["api_source"].value_counts().rename("jobs").to_frame()
    source["share_pct"] = (source["jobs"] / total * 100).round(2)
    add_section(lines, "SOURCE MIX", table(source))

    roles = jobs["role_family"].value_counts().rename("jobs").to_frame()
    roles["share_pct"] = (roles["jobs"] / total * 100).round(2)
    add_section(lines, "ROLE FAMILIES", table(roles))

    rules = jobs["role_rule"].value_counts().rename("jobs").to_frame()
    rules["share_pct"] = (rules["jobs"] / total * 100).round(2)
    add_section(lines, "ROLE CLASSIFICATION RULES", table(rules))

    skill_counts = (
        skills.groupby("skill")["job_id"].nunique().sort_values(ascending=False)
    )
    top_skills = skill_counts.head(20).rename("jobs").to_frame()
    top_skills["share_all_jobs_pct"] = (top_skills["jobs"] / total * 100).round(2)
    top_skills["share_skill_tagged_pct"] = (
        top_skills["jobs"] / max(skill_tagged, 1) * 100
    ).round(2)
    add_section(lines, "TOP 20 SKILLS", table(top_skills))

    experience = (
        jobs["experience_band"]
        .fillna("Not Specified")
        .value_counts()
        .rename("jobs")
        .to_frame()
    )
    experience["share_pct"] = (experience["jobs"] / total * 100).round(2)
    add_section(lines, "EXPERIENCE BANDS", table(experience))

    seniority = (
        jobs["seniority_level"]
        .fillna("Not Specified")
        .value_counts()
        .rename("jobs")
        .to_frame()
    )
    seniority["share_pct"] = (seniority["jobs"] / total * 100).round(2)
    add_section(lines, "SENIORITY", table(seniority))

    role_opportunity = jobs.groupby("role_family").agg(
        jobs=("job_id", "nunique"),
        explicit_experience=("experience_explicit_flag", "sum"),
        entry_level=("entry_level_flag", "sum"),
    )
    role_opportunity["experience_coverage_pct"] = (
        role_opportunity["explicit_experience"] / role_opportunity["jobs"] * 100
    ).round(2)
    role_opportunity["entry_level_share_pct"] = (
        role_opportunity["entry_level"] / role_opportunity["jobs"] * 100
    ).round(2)
    role_opportunity = role_opportunity.sort_values("jobs", ascending=False)
    add_section(
        lines, "EXPERIENCE AND ENTRY-LEVEL OPPORTUNITY BY ROLE", table(role_opportunity)
    )

    known_city = jobs.loc[jobs["location_scope"].eq("Specific City"), "city"]
    city = known_city.value_counts().head(20).rename("jobs").to_frame()
    city["share_known_city_pct"] = (city["jobs"] / max(len(known_city), 1) * 100).round(
        2
    )
    add_section(lines, "TOP 20 CITY LABELS", table(city))

    date_basis = (
        jobs.groupby(["api_source", "posting_date_basis"])
        .size()
        .rename("jobs")
        .unstack(fill_value=0)
    )
    add_section(lines, "DATE BASIS BY SOURCE", table(date_basis))

    monthly = (
        observed.groupby(observed["posted_date"].dt.to_period("M"))
        .size()
        .rename("observed_jobs")
    )
    add_section(lines, "MONTHLY POSTINGS — OBSERVED DATES ONLY", table(monthly))

    salary_by_source = jobs.groupby("api_source").agg(
        total_jobs=("job_id", "size"),
        salary_eligible=("salary_analysis_eligible", "sum"),
    )
    salary_by_source["eligible_pct"] = (
        salary_by_source["salary_eligible"] / salary_by_source["total_jobs"] * 100
    ).round(2)
    add_section(lines, "SALARY COVERAGE BY SOURCE", table(salary_by_source))

    if not salary.empty:
        salary_mid = pd.to_numeric(salary["salary_midpoint"], errors="coerce")
        salary_summary = pd.Series(
            {
                "eligible_rows": int(salary_mid.notna().sum()),
                "median_salary": salary_mid.median(),
                "mean_salary": salary_mid.mean(),
                "p25_salary": salary_mid.quantile(0.25),
                "p75_salary": salary_mid.quantile(0.75),
                "minimum_salary": salary_mid.min(),
                "maximum_salary": salary_mid.max(),
            }
        )
        add_section(lines, "NORMALIZED SALARY SUMMARY", table(salary_summary.round(2)))

    role_source = pd.crosstab(jobs["role_family"], jobs["api_source"])
    add_section(lines, "ROLE FAMILY BY SOURCE — COUNTS", table(role_source))

    role_skills = (
        jobs[["job_id", "role_family"]]
        .merge(skills[["job_id", "skill"]], on="job_id", how="inner")
        .groupby(["role_family", "skill"])["job_id"]
        .nunique()
        .rename("jobs")
        .reset_index()
    )
    role_skills["rank"] = role_skills.groupby("role_family")["jobs"].rank(
        method="first", ascending=False
    )
    top_role_skills = role_skills[role_skills["rank"].le(5)].sort_values(
        ["role_family", "rank"]
    )
    add_section(
        lines,
        "TOP FIVE SKILLS WITHIN EACH ROLE FAMILY",
        table(
            top_role_skills[["role_family", "skill", "jobs"]].set_index(
                ["role_family", "skill"]
            )
        ),
    )

    general = jobs[jobs["role_family"].eq("General Analytics Analyst")]
    general_titles = general["title"].value_counts().head(30)
    add_section(
        lines,
        "GENERAL ANALYTICS BUCKET AUDIT",
        f"Jobs: {len(general):,} ({len(general) / total:.2%})\n\n{table(general_titles)}",
    )

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("=" * 72)
    print("FINAL ANALYSIS PROFILE CREATED")
    print("=" * 72)
    print(f"Final unique jobs:        {total:,}")
    print(f"Skill-tagged jobs:        {skill_tagged:,}")
    print(f"Observed-date jobs:       {len(observed):,}")
    print(f"Salary-analysis rows:     {len(salary):,}")
    print(f"Report:                   {REPORT_FILE}")


if __name__ == "__main__":
    main()
