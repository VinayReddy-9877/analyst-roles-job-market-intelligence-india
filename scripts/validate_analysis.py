"""Validate the frozen reporting tables against the dataset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

from pbixray import PBIXRay


import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "config" / "dataset_lock.json"
JOBS_FILE = ROOT / "data" / "processed" / "job_postings_clean.csv"
SKILLS_FILE = ROOT / "data" / "processed" / "job_skills_bridge.csv"
REPORT_FILE = ROOT / "reports" / "validation_report.txt"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
DASHBOARD_DIR = ROOT / "dashboard"
PBIX_FILE = DASHBOARD_DIR / "DataAnalystJobMarketIntelligence.pbix"
DAX_FILE = DASHBOARD_DIR / "DAX_MEASURES"
SCREENSHOT_DIR = DASHBOARD_DIR / "screenshots"

EXPECTED_SCREENSHOTS = [
    "01_executive_overview.png",
    "02_skills_and_experience.png",
    "03_salary_insights.png",
    "04_role_and_location.png",
    "05_trends_and_statistical.png",
]
TREND_CAUTION = (
    "Older postings may have been delisted before collection, "
    "so earlier weeks are undercounted"
)

JOB_COLUMNS = {
    "job_id",
    "company_name",
    "role_family",
    "source_family",
    "specific_city",
    "posted_date",
    "created_at",
    "posting_date_basis",
    "experience_explicit_flag",
    "salary_min",
    "salary_max",
    "salary_midpoint",
    "salary_analysis_eligible",
    "skill_count",
    "has_extracted_skill",
    "is_recent_90d",
    "is_complete_week",
    "is_posting_date_observed",
}
SKILL_COLUMNS = {"job_id", "skill", "skill_category"}

PBIX_JOB_FIELDS = {
    "Job ID": "job_id",
    "Job Key": "job_key",
    "Title": "title",
    "Role Family": "role_family",
    "Company": "company_name",
    "City": "city",
    "State": "state",
    "Location Scope": "location_scope",
    "Work Mode": "work_mode",
    "Experience Band": "experience_band",
    "Salary Midpoint": "salary_midpoint",
    "Salary Analysis Eligible": "salary_analysis_eligible",
    "Skill Count": "skill_count",
    "Has Extracted Skill": "has_extracted_skill",
    "Recent 90D": "is_recent_90d",
    "Complete Week": "is_complete_week",
    "Source Family": "source_family",
    "Specific City": "specific_city",
}
PBIX_SKILL_FIELDS = {
    "Job ID": "job_id",
    "Role Family": "role_family",
    "Company": "company_name",
    "City": "city",
    "State": "state",
    "Location Scope": "location_scope",
    "Work Mode": "work_mode",
    "Experience Band": "experience_band",
    "Salary Midpoint": "salary_midpoint",
    "Salary Analysis Eligible": "salary_analysis_eligible",
    "Recent 90D": "is_recent_90d",
    "Complete Week": "is_complete_week",
    "Skill": "skill",
    "Skill Category": "skill_category",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    values = series.astype("string").str.strip().str.lower()
    valid = {"true", "false", "1", "0", "yes", "no"}
    unexpected = set(values.dropna().unique()) - valid
    if unexpected:
        raise ValueError(f"Unexpected boolean values: {sorted(unexpected)}")
    return values.isin({"true", "1", "yes"})


def png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        header = path.read_bytes()[:24]
    except OSError:
        return None
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


def read_pbix_report() -> tuple[list[str], list[dict]]:
    page_names: dict[str, str] = {}
    visuals: list[dict] = []
    with zipfile.ZipFile(PBIX_FILE) as archive:
        for name in archive.namelist():
            parts = name.split("/")
            if len(parts) == 5 and parts[:3] == ["Report", "definition", "pages"]:
                if parts[-1] == "page.json":
                    page = json.loads(archive.read(name).decode("utf-8"))
                    page_names[parts[3]] = page["displayName"].strip()
        for name in archive.namelist():
            parts = name.split("/")
            if (
                len(parts) == 7
                and parts[:3] == ["Report", "definition", "pages"]
                and parts[-1] == "visual.json"
            ):
                item = json.loads(archive.read(name).decode("utf-8"))
                item["page_name"] = page_names.get(parts[3], parts[3])
                visuals.append(item)
    return sorted(page_names.values()), visuals


def pbix_rows_match(
    model_table: pd.DataFrame,
    source_table: pd.DataFrame,
    fields: dict[str, str],
    sort_columns: list[str],
) -> bool:
    """Compare selected semantic-model fields with their source CSV columns."""
    model = model_table[list(fields)].rename(columns=fields).copy()
    source = source_table[list(fields.values())].copy()
    model = model.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    source = source.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    if len(model) != len(source):
        return False

    for column in fields.values():
        left = model[column]
        right = source[column]
        if column in {
            "salary_analysis_eligible",
            "has_extracted_skill",
            "is_recent_90d",
            "is_complete_week",
        }:
            if not as_bool(left).equals(as_bool(right)):
                return False
        elif column in {"salary_midpoint", "skill_count"}:
            left_number = pd.to_numeric(left, errors="coerce")
            right_number = pd.to_numeric(right, errors="coerce")
            if not np.allclose(left_number, right_number, equal_nan=True):
                return False
        else:
            left_text = left.astype("string").fillna("")
            right_text = right.astype("string").fillna("")
            if not left_text.equals(right_text):
                return False
    return True


def main(scope: str = "data") -> int:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    jobs = pd.read_csv(JOBS_FILE, low_memory=False)
    skills = pd.read_csv(SKILLS_FILE, low_memory=False)
    results: list[tuple[str, bool]] = []

    def check(label: str, condition: bool) -> None:
        results.append((label, bool(condition)))

    for relative_path, expected in lock["sha256"].items():
        if scope == "data" and not relative_path.startswith("data/processed/"):
            continue
        path = ROOT / relative_path
        check(
            f"SHA-256: {relative_path}",
            path.exists() and file_hash(path) == expected.lower(),
        )

    check("Jobs table has required columns", JOB_COLUMNS <= set(jobs.columns))
    check("Skills table has required columns", SKILL_COLUMNS <= set(skills.columns))

    for column in (
        "experience_explicit_flag",
        "salary_analysis_eligible",
        "has_extracted_skill",
        "is_recent_90d",
        "is_complete_week",
        "is_posting_date_observed",
    ):
        jobs[column] = as_bool(jobs[column])

    check("Unique job count", len(jobs) == lock["final_unique_jobs"])
    check("Job-skill row count", len(skills) == lock["skill_bridge_rows"])
    check("Distinct skill count", skills["skill"].nunique() == lock["unique_skills"])
    check(
        "Job IDs are unique and populated",
        jobs["job_id"].notna().all() and jobs["job_id"].is_unique,
    )
    check(
        "Job-skill pairs are unique", not skills.duplicated(["job_id", "skill"]).any()
    )
    check(
        "Skills contain no orphan job IDs", set(skills["job_id"]) <= set(jobs["job_id"])
    )

    bridge_counts = skills.groupby("job_id")["skill"].nunique()
    expected_skill_counts = jobs["job_id"].map(bridge_counts).fillna(0).astype(int)
    check(
        "Job skill counts match the bridge",
        expected_skill_counts.eq(jobs["skill_count"]).all(),
    )
    check(
        "Skill coverage flags match the bridge",
        jobs["has_extracted_skill"].eq(expected_skill_counts.gt(0)).all(),
    )
    check(
        "Skill-tagged job count",
        int(jobs["has_extracted_skill"].sum()) == lock["skill_tagged_jobs"],
    )

    dates_present = jobs["posted_date"].notna() & jobs["created_at"].notna()
    date_basis = jobs["posting_date_basis"].value_counts().to_dict()
    check("Reporting dates are populated", dates_present.all())
    check(
        "Observed/proxy date split",
        date_basis
        == {
            "source_posted_at": lock["observed_dated_jobs"],
            "source_updated_at_proxy": lock["proxy_dated_jobs"],
        },
    )

    observed = jobs["is_posting_date_observed"]
    recent = jobs["is_recent_90d"]
    complete = jobs["is_complete_week"]
    check(
        "Observed-date flag agrees with provenance",
        observed.eq(jobs["posting_date_basis"].isin(["source_created_at", "source_posted_at"])).all(),
    )
    check("Recent postings require observed dates", not (recent & ~observed).any())
    check("Complete weeks require observed dates", not (complete & ~observed).any())
    check("Recent observed posting count", int((recent & observed).sum()) == 3506)
    check("Earlier observed posting count", int((~recent & observed).sum()) == 382)
    check("Proxy-dated posting count", int((~observed).sum()) == 1572)

    check(
        "Specific-city job count",
        int(jobs["specific_city"].notna().sum()) == lock["specific_city_jobs"],
    )
    check(
        "Specific-city label count",
        jobs["specific_city"].nunique() == lock["specific_city_labels"],
    )
    check(
        "Source mix",
        jobs["source_family"].value_counts().to_dict() == lock["source_mix"],
    )

    eligible = jobs["salary_analysis_eligible"]
    salary = jobs.loc[eligible, ["salary_min", "salary_max", "salary_midpoint"]]
    midpoint = (salary["salary_min"] + salary["salary_max"]) / 2
    check(
        "Salary-eligible row count",
        int(eligible.sum()) == lock["salary_analysis_eligible"],
    )
    check(
        "Eligible salaries are complete and positive",
        salary.notna().all().all() and (salary > 0).all().all(),
    )
    check(
        "Salary midpoints match min/max",
        np.isclose(salary["salary_midpoint"], midpoint).all(),
    )

    headline = lock["headline_checks"]
    roles = jobs["role_family"].value_counts()
    skill_jobs = skills.groupby("skill")["job_id"].nunique()
    city_jobs = jobs["specific_city"].value_counts()
    check(
        "Top role result",
        int(roles[headline["top_role_family"]]) == headline["top_role_jobs"],
    )
    check(
        "Top skill result",
        int(skill_jobs[headline["top_skill"]]) == headline["top_skill_jobs"],
    )
    check(
        "Top city result",
        int(city_jobs[headline["top_specific_city"]])
        == headline["top_specific_city_jobs"],
    )

    # A missing SQL tag and missing skills altogether are not equivalent.
    sql_ids = set(skills.loc[skills["skill"].eq("SQL"), "job_id"])
    sql_mask = eligible & jobs["job_id"].isin(sql_ids)
    other_mask = eligible & ~jobs["job_id"].isin(sql_ids) & jobs["has_extracted_skill"]
    unknown_mask = eligible & ~jobs["has_extracted_skill"]
    group_masks = {
        "SQL detected": sql_mask,
        "Other skills detected (no SQL tag)": other_mask,
        "No skills extracted (unknown)": unknown_mask,
    }
    check(
        "Salary-evidence groups partition eligible postings",
        sum(int(mask.sum()) for mask in group_masks.values()) == int(eligible.sum())
        and not (sql_mask & other_mask).any()
        and not (sql_mask & unknown_mask).any()
        and not (other_mask & unknown_mask).any(),
    )
    check("SQL-detected salary observations", int(sql_mask.sum()) == 43)
    check("Other-skill-detected salary observations", int(other_mask.sum()) == 16)
    check("Unknown-skill salary observations", int(unknown_mask.sum()) == 33)

    evidence_file = REPORTS_DIR / "salary_skill_evidence.csv"
    regression_file = REPORTS_DIR / "salary_regression_summary.txt"
    check("Three-group salary evidence report exists", evidence_file.is_file())
    check("Adjusted salary regression summary exists", regression_file.is_file())

    if evidence_file.is_file():
        evidence_report = pd.read_csv(evidence_file)
        required = {"source_family", "skill_evidence_group", "salary_n", "median"}
        if required <= set(evidence_report.columns):
            overall_groups = evidence_report.loc[
                evidence_report["source_family"].eq("All sources")
            ].set_index("skill_evidence_group")
            group_match = set(overall_groups.index) == set(group_masks)
            for label, mask in group_masks.items():
                if label not in overall_groups.index:
                    group_match = False
                    continue
                actual = overall_groups.loc[label]
                observed_median = jobs.loc[mask, "salary_midpoint"].median()
                group_match &= int(actual["salary_n"]) == int(mask.sum())
                group_match &= bool(np.isclose(float(actual["median"]), observed_median))
            check("Salary evidence CSV reconciles to raw group medians", group_match)
        else:
            check("Salary evidence CSV has required columns", False)

    if regression_file.is_file():
        regression_text = regression_file.read_text(encoding="utf-8")
        check(
            "Regression summary has correctly scoped sample and caveats",
            "Regression sample: 59" in regression_text
            and "Conditional association:" in regression_text
            and "Model p-value:" in regression_text
            and "not causal" in regression_text.lower(),
        )

    city_report = pd.read_csv(REPORTS_DIR / "city_demand_summary.csv")
    check(
        "City report has one row per city label",
        city_report["city"].is_unique
        and len(city_report) == lock["specific_city_labels"],
    )
    check(
        "City report reconciles to specific-city jobs",
        int(city_report["job_count"].sum()) == lock["specific_city_jobs"],
    )

    experience_report = pd.read_csv(REPORTS_DIR / "experience_distribution.csv")
    unspecified_share = experience_report.loc[
        experience_report["experience_band"].eq("Not Specified"),
        "share_of_labeled_jobs_pct",
    ]
    labeled_shares = experience_report.loc[
        experience_report["experience_band"].ne("Not Specified"),
        "share_of_labeled_jobs_pct",
    ]
    check(
        "Experience report reconciles to all jobs",
        int(experience_report["job_count"].sum()) == len(jobs),
    )
    check(
        "Experience labeled shares exclude unspecified jobs",
        len(unspecified_share) == 1
        and unspecified_share.isna().all()
        and np.isclose(labeled_shares.sum(), 100, atol=0.05),
    )

    weekly_report = pd.read_csv(REPORTS_DIR / "weekly_hiring_trend.csv")
    complete_week_count = jobs.loc[
        jobs["is_complete_week"] & jobs["posting_date_basis"].eq("source_posted_at"),
        "week_start",
    ].nunique()
    check(
        "Weekly trend contains complete observed weeks only",
        len(weekly_report) == complete_week_count,
    )

    refreshed_figures = {
        "01_role_distribution.png",
        "02_city_demand.png",
        "04_top_skills.png",
        "05_skill_cooccurrence.png",
        "06_salary_distribution.png",
        "09_weekly_job_demand.png",
        "11_sql_salary_comparison.png",
    }
    check(
        "Required refreshed figures exist",
        all(
            (FIGURES_DIR / name).is_file()
            and (FIGURES_DIR / name).stat().st_size > 0
            for name in refreshed_figures
        ),
    )

    if scope == "all":
        dax_text = DAX_FILE.read_text(encoding="utf-8")
        check(
            "Unused analyst measures are absent",
            "Other Analyst Jobs" not in dax_text
            and "Other Analyst Share %" not in dax_text,
        )
        check(
            "Complete-week trend measures are documented",
            "Complete Week Jobs =" in dax_text and "Complete Weeks =" in dax_text,
        )

        page_names, visuals = read_pbix_report()
        check(
            "Power BI report contains the five expected pages",
            page_names
            == sorted(
                [
                    "Executive Overview",
                    "Role & Location",
                    "Salary Insights",
                    "Skills & Experience",
                    "Trends & Statistical",
                ]
            ),
        )
        card_count = sum(
            visual.get("visual", {}).get("visualType") == "card" for visual in visuals
        )
        check("Power BI report contains 30 Card visuals", card_count == 30)

        line_visuals = [
            visual
            for visual in visuals
            if visual.get("visual", {}).get("visualType") == "lineChart"
        ]
        line_text = [json.dumps(visual, ensure_ascii=False) for visual in line_visuals]
        check(
            "Trend charts use Week Start and Complete Week Jobs",
            len(line_visuals) >= 2
            and all('"Property": "Week Start"' in text for text in line_text)
            and all('"Property": "Complete Week Jobs"' in text for text in line_text),
        )
        check(
            "Trend charts carry the collection-bias annotation",
            all(TREND_CAUTION in text for text in line_text),
        )

        report_text = "\n".join(json.dumps(item, ensure_ascii=False) for item in visuals)
        check(
            "Experience distribution uses a bar chart",
            any(
                item.get("page_name") == "Skills & Experience"
                and item.get("visual", {}).get("visualType") == "barChart"
                and "Experience Band" in json.dumps(item, ensure_ascii=False)
                for item in visuals
            ),
        )
        check(
            "Work-mode chart is framed as disclosure",
            "Work Mode Disclosure" in report_text
            and "Only 19.7% of postings specify work mode" in report_text,
        )
        check(
            "Report visuals do not reference unused analyst measures",
            "Other Analyst Jobs" not in report_text
            and "Other Analyst Share %" not in report_text,
        )

        salary_visuals = [
            item for item in visuals if item.get("page_name") == "Salary Insights"
        ]
        salary_chart_types = sorted(
            item.get("visual", {}).get("visualType")
            for item in salary_visuals
            if item.get("visual", {}).get("visualType")
            in {"barChart", "columnChart", "donutChart"}
        )
        salary_text = "\n".join(
            json.dumps(item, ensure_ascii=False) for item in salary_visuals
        )
        check(
            "Salary page does not make the obsolete SQL/non-SQL comparison",
            "SQL vs Non-SQL Salary" not in salary_text
            and "SQL vs Non-SQL Salary Midpoints" not in salary_text,
        )

        model = PBIXRay(str(PBIX_FILE))
        try:
            model_measures = model.dax_measures.set_index("Name")["Expression"]
            check(
                "Power BI model excludes unused analyst measures",
                "Other Analyst Jobs" not in model_measures.index
                and "Other Analyst Share %" not in model_measures.index,
            )
            check(
                "Power BI model has no obsolete full-sample salary-bootstrap measures",
                "Overall Bootstrap CI Lower (₹L)" not in model_measures.index
                and "Overall Bootstrap CI Upper (₹L)" not in model_measures.index,
            )
            model_jobs = model.get_table("Jobs")
            model_skills = model.get_table("Skills")
            check(
                "Power BI Jobs table matches the processed CSV",
                pbix_rows_match(
                    model_jobs,
                    jobs,
                    PBIX_JOB_FIELDS,
                    ["job_id"],
                ),
            )
            check(
                "Power BI Skills table matches the processed CSV",
                pbix_rows_match(
                    model_skills,
                    skills,
                    PBIX_SKILL_FIELDS,
                    ["job_id", "skill"],
                ),
            )
        finally:
            model.close()

        screenshot_names = sorted(path.name for path in SCREENSHOT_DIR.glob("*.png"))
        screenshot_sizes = [
            png_dimensions(SCREENSHOT_DIR / name) for name in EXPECTED_SCREENSHOTS
        ]
        check(
            "Recruiter preview contains all five dashboard pages",
            screenshot_names == EXPECTED_SCREENSHOTS
            and all(
                size is not None
                and size[0] >= 990
                and size[1] >= 560
                and abs((size[0] / size[1]) - (16 / 9)) < 0.02
                for size in screenshot_sizes
            ),
        )

    passed = all(result for _, result in results)
    lines = [
        "DATA ANALYST JOB MARKET INTELLIGENCE — VALIDATION",
        "=" * 62,
        f"dataset_freeze_date: {lock['dataset_freeze_date']}",
        f"jobs: {len(jobs):,}",
        f"job_skill_rows: {len(skills):,}",
        f"scope: {scope}",
        f"status: {'PASS' if passed else 'FAIL'}",
        "",
    ]
    lines.extend(
        f"{'PASS' if result else 'FAIL'}  {label}" for label, result in results
    )
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate frozen job-market analytics")
    parser.add_argument(
        "--scope", choices=["data", "all"], default="data",
        help="Use 'all' only after updating Power BI visuals and semantic model",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.scope))
