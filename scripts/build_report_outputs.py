"""Regenerate report tables and figures from the frozen processed tables."""

from __future__ import annotations

import itertools
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"


def _share(
    frame: pd.DataFrame, denominator: int, column: str = "job_count"
) -> pd.DataFrame:
    frame = frame.copy()
    frame["share_pct"] = (frame[column] / denominator * 100).round(2)
    return frame


def _salary_summary(values: pd.Series) -> dict[str, float | int]:
    values = values.dropna()
    return {
        "salary_n": int(values.size),
        "p25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "p75": float(values.quantile(0.75)),
        "mean": float(values.mean()),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def _group_salary(jobs: pd.DataFrame, column: str) -> pd.DataFrame:
    eligible = jobs.loc[jobs["salary_analysis_eligible"]].copy()
    eligible = eligible.loc[eligible[column].notna()]
    rows = []
    for value, group in eligible.groupby(column, dropna=False):
        item = {column: value}
        item.update(_salary_summary(group["salary_midpoint"]))
        rows.append(item)
    return pd.DataFrame(rows).sort_values("salary_n", ascending=False)


def build_salary_skill_evidence(jobs: pd.DataFrame, skills: pd.DataFrame) -> str:
    """Compare salaries only where the posting explicitly yields skill evidence.

    Missing extracted skills are their own group; they must not be described as
    employers explicitly not requiring SQL. Adjusted estimates are descriptive.
    """
    eligible = jobs.loc[jobs["salary_analysis_eligible"]].copy()
    sql_ids = set(skills.loc[skills["skill"].eq("SQL"), "job_id"])
    eligible["sql_detected"] = eligible["job_id"].isin(sql_ids)
    eligible["skill_evidence_group"] = np.select(
        [eligible["sql_detected"], eligible["has_extracted_skill"]],
        ["SQL detected", "Other skills detected (no SQL tag)"],
        default="No skills extracted (unknown)",
    )
    grouped = []
    for (name, source), frame in eligible.groupby(
        ["skill_evidence_group", "source_family"], sort=True
    ):
        row = {"skill_evidence_group": name, "source_family": source}
        row.update(_salary_summary(frame["salary_midpoint"]))
        grouped.append(row)
    all_sources = []
    for name, frame in eligible.groupby("skill_evidence_group", sort=True):
        row = {"skill_evidence_group": name, "source_family": "All sources"}
        row.update(_salary_summary(frame["salary_midpoint"]))
        all_sources.append(row)
    pd.DataFrame(all_sources + grouped).to_csv(
        REPORTS / "salary_skill_evidence.csv", index=False
    )

    known = eligible.loc[
        eligible["sql_detected"] | eligible["has_extracted_skill"]
    ].copy()
    # Sparse data: use two source families and collapse three observed seniority
    # categories into two; retain missing-experience indicators, not fake zeros.
    known["log_salary"] = np.log(known["salary_midpoint"])
    known["sql_flag"] = known["sql_detected"].astype(int)
    known["seniority_group"] = known["seniority_level"].replace(
        {"Senior": "Senior / Manager", "Lead / Manager": "Senior / Manager"}
    )
    known["experience_years"] = known["experience_min_years"].fillna(0)
    known["experience_missing"] = known["experience_min_years"].isna().astype(int)
    formula = (
        "log_salary ~ sql_flag + C(source_family) + C(seniority_group) "
        "+ experience_years + experience_missing"
    )
    model = smf.ols(formula, data=known).fit(cov_type="HC3")
    coefficient = float(model.params["sql_flag"])
    low, high = model.conf_int().loc["sql_flag"].astype(float)
    percent = (np.exp(coefficient) - 1) * 100
    ci_low, ci_high = (np.exp([low, high]) - 1) * 100
    lines = [
        "Advertised salary and SQL detection: conditional exploratory analysis",
        "======================================================================",
        f"Salary-eligible postings: {len(eligible)}",
        f"SQL detected: {eligible['sql_detected'].sum()}",
        f"Other extracted skills, no SQL tag: {((~eligible['sql_detected']) & eligible['has_extracted_skill']).sum()}",
        f"Skills not extracted: {(~eligible['has_extracted_skill']).sum()}",
        f"Regression sample: {len(known)} disclosed-salary jobs with extracted-skill evidence",
        "Model: log(midpoint advertised annual INR salary) ~ SQL detection + source "
        "+ seniority + minimum years of experience + experience missingness",
        "Heteroskedasticity-robust HC3 confidence interval (95%).",
        f"Conditional association: {percent:.1f}% (95% CI {ci_low:.1f}% to {ci_high:.1f}%).",
        f"Model p-value: {float(model.pvalues['sql_flag']):.3f}.",
        "This association is not causal and is not generalizable to all job postings.",
        "Unspecified or poorly described skills cannot be treated as an explicit no-SQL requirement.",
        "Controls are necessarily coarse: n is small and only postings with salary data are included.",
    ]
    report = "\n".join(lines) + "\n"
    (REPORTS / "salary_regression_summary.txt").write_text(report, encoding="utf-8")
    return report


def build_source_period_skill_summary(jobs: pd.DataFrame, skills: pd.DataFrame) -> None:
    """Show comparable observed-date periods by source and skill coverage."""
    observed = jobs.loc[jobs["is_posting_date_observed"]].copy()
    observed["period"] = np.where(
        observed["is_recent_90d"], "Recent 90 days", "Earlier observed"
    )
    records = []
    for (source, period), frame in observed.groupby(["source_family", "period"]):
        job_ids = set(frame["job_id"])
        tagged = int(frame["has_extracted_skill"].sum())
        for skill in ["SQL", "Excel", "Power BI", "Python", "Tableau"]:
            skill_ids = set(skills.loc[skills["skill"].eq(skill), "job_id"])
            count = len(job_ids.intersection(skill_ids))
            records.append({
                "source_family": source,
                "period": period,
                "skill": skill,
                "total_jobs": len(frame),
                "tagged_jobs": tagged,
                "skill_jobs": count,
                "skill_share_pct": round(100 * count / len(frame), 2),
                "skill_coverage_pct": round(100 * tagged / len(frame), 2),
            })
    pd.DataFrame(records).to_csv(
        REPORTS / "source_period_skill_summary.csv", index=False
    )


def metro_area(city: str) -> str:
    """Group known commuter markets without treating state labels as cities."""
    areas = {
        "Delhi NCR": {"Delhi", "New Delhi", "Gurugram", "Noida", "Greater Noida", "Ghaziabad", "Faridabad"},
        "Hyderabad Metro": {"Hyderabad", "Secunderabad", "Gachibowli", "HITEC City"},
        "Mumbai Metro": {"Mumbai", "Navi Mumbai", "Thane"},
        "Bengaluru Metro": {"Bengaluru"},
    }
    for label, members in areas.items():
        if city in members:
            return label
    return city


def _preferred_state(values: pd.Series) -> str:
    """Return the most common known state for a normalized city label."""
    known = values.dropna().loc[lambda item: item.ne("Unknown")]
    if known.empty:
        return "Unknown"
    return str(known.mode().iloc[0])


def _write_figures(jobs: pd.DataFrame, skills: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    def save(name: str) -> None:
        plt.tight_layout()
        plt.savefig(FIGURES / name, dpi=160, bbox_inches="tight")
        plt.close()

    role = jobs["role_family"].value_counts().head(10).sort_values()
    role.plot.barh(color="#2b6cb0", title="Top role families by postings")
    plt.xlabel("Postings")
    save("01_role_distribution.png")

    city = jobs["specific_city"].dropna().value_counts().head(10).sort_values()
    city.plot.barh(color="#2f855a", title="Top specific-city markets")
    plt.xlabel("Postings")
    save("02_city_demand.png")

    skill = skills["skill"].value_counts().head(10).sort_values()
    skill.plot.barh(color="#805ad5", title="Top extracted skills")
    plt.xlabel("Distinct jobs")
    save("04_top_skills.png")

    salary = jobs.loc[jobs["salary_analysis_eligible"], "salary_midpoint"] / 100_000
    plt.figure(figsize=(7, 4))
    plt.hist(salary, bins=12, color="#dd6b20", edgecolor="white")
    plt.title("Eligible advertised salary distribution")
    plt.xlabel("Salary midpoint (INR lakhs)")
    plt.ylabel("Eligible postings")
    save("06_salary_distribution.png")

    complete = jobs.loc[
        jobs["is_posting_date_observed"] & jobs["is_complete_week"]
    ].copy()
    weekly = complete.groupby("week_start").size()
    plt.figure(figsize=(8, 4))
    plt.plot(pd.to_datetime(weekly.index), weekly.values, color="#2b6cb0", linewidth=2)
    plt.title("Job postings by complete observed week")
    plt.xlabel("Week starting")
    plt.ylabel("Postings")
    save("09_weekly_job_demand.png")

    pairs: list[tuple[str, str]] = []
    for _, group in skills.groupby("job_id")["skill"]:
        pairs.extend(itertools.combinations(sorted(set(group)), 2))
    pair_counts = pd.Series(pairs).value_counts().head(10).sort_values()
    labels = [f"{left} + {right}" for left, right in pair_counts.index]
    plt.figure(figsize=(8, 5))
    plt.barh(labels, pair_counts.values, color="#3182ce")
    plt.title("Top skill co-occurrence pairs")
    plt.xlabel("Distinct jobs")
    save("05_skill_cooccurrence.png")

    sql_ids = set(skills.loc[skills["skill"].eq("SQL"), "job_id"])
    sql_mask = jobs["job_id"].isin(sql_ids)
    eligible = jobs["salary_analysis_eligible"]
    groups = [
        jobs.loc[eligible & sql_mask, "salary_midpoint"] / 100_000,
        jobs.loc[eligible & ~sql_mask & jobs["has_extracted_skill"], "salary_midpoint"] / 100_000,
        jobs.loc[eligible & ~jobs["has_extracted_skill"], "salary_midpoint"] / 100_000,
    ]
    plt.figure(figsize=(8, 4))
    plt.boxplot(
        groups,
        tick_labels=["SQL detected", "Other skills", "Unknown skills"],
        patch_artist=True,
        boxprops={"facecolor": "#63b3ed"},
        medianprops={"color": "#1a365d", "linewidth": 2},
    )
    plt.ylabel("Advertised salary midpoint (INR lakhs)")
    plt.title("Skill-evidence groups in 92 salary records")
    save("11_sql_salary_comparison.png")


def main() -> None:
    jobs = pd.read_csv(ROOT / "data" / "processed" / "job_postings_clean.csv")
    skills = pd.read_csv(ROOT / "data" / "processed" / "job_skills_bridge.csv")
    REPORTS.mkdir(exist_ok=True)

    roles = (
        jobs["role_family"]
        .value_counts()
        .rename_axis("role_family")
        .reset_index(name="job_count")
    )
    _share(roles, len(jobs)).to_csv(REPORTS / "role_demand_summary.csv", index=False)

    city_jobs = jobs.loc[jobs["specific_city"].notna()]
    cities = (
        city_jobs.groupby("specific_city", dropna=False)
        .agg(state=("state", _preferred_state), job_count=("job_id", "size"))
        .reset_index()
        .rename(columns={"specific_city": "city"})
        .sort_values("job_count", ascending=False)
    )
    cities["metro_area"] = cities["city"].map(metro_area)
    _share(cities, len(jobs)).to_csv(REPORTS / "city_demand_summary.csv", index=False)

    # Keep city-role and city-skill evidence separate from national counts.
    # The top five city markets are detailed for stakeholder use.
    top_cities = set(cities.head(5)["city"])
    city_jobs = city_jobs.loc[city_jobs["specific_city"].isin(top_cities)]
    city_roles = (
        city_jobs.groupby(["specific_city", "role_family"]).size()
        .reset_index(name="posting_count")
        .rename(columns={"specific_city": "city", "role_family": "category"})
    )
    city_roles.insert(1, "dimension", "role")
    city_skills = (
        skills[["job_id", "skill"]].merge(
            city_jobs[["job_id", "specific_city"]], on="job_id", how="inner"
        ).groupby(["specific_city", "skill"]).size()
        .reset_index(name="posting_count")
        .rename(columns={"specific_city": "city", "skill": "category"})
    )
    city_skills.insert(1, "dimension", "skill")
    pd.concat([city_roles, city_skills], ignore_index=True).to_csv(
        REPORTS / "city_role_skill_summary.csv", index=False
    )

    companies = (
        jobs.loc[jobs["company_name"] != "Unknown Company", "company_name"]
        .value_counts()
        .rename_axis("company_name")
        .reset_index(name="job_count")
    )
    _share(companies, len(jobs)).to_csv(
        REPORTS / "company_demand_summary.csv", index=False
    )

    skill_counts = (
        skills.groupby("skill")["job_id"].nunique().sort_values(ascending=False)
    )
    skill_table = skill_counts.rename("job_count").rename_axis("skill").reset_index()
    categories = skills.drop_duplicates(["skill"])[["skill", "skill_category"]]
    skill_table = skill_table.merge(categories, on="skill", how="left")
    skill_table["share_of_all_jobs_pct"] = (
        skill_table["job_count"] / len(jobs) * 100
    ).round(2)
    skill_table["share_of_skill_tagged_jobs_pct"] = (
        skill_table["job_count"] / jobs["has_extracted_skill"].sum() * 100
    ).round(2)
    skill_table.to_csv(REPORTS / "skill_demand_summary.csv", index=False)

    high_coverage_job_ids = jobs.loc[
        jobs["source_family"].isin(["Freehire", "JSearch"]), "job_id"
    ]
    restricted_skill_counts = (
        skills.loc[skills["job_id"].isin(high_coverage_job_ids)]
        .groupby("skill")["job_id"]
        .nunique()
        .sort_values(ascending=False)
        .head(10)
        .rename("high_coverage_source_jobs")
        .rename_axis("skill")
        .reset_index()
    )
    restricted_skill_counts.insert(
        0, "rank", range(1, len(restricted_skill_counts) + 1)
    )
    restricted_skill_counts.to_csv(
        REPORTS / "skill_source_sensitivity.csv", index=False
    )

    experience = (
        jobs["experience_band"]
        .value_counts()
        .rename_axis("experience_band")
        .reset_index(name="job_count")
    )
    experience["share_of_all_jobs_pct"] = (
        experience["job_count"] / len(jobs) * 100
    ).round(2)
    labeled_jobs = int(jobs["experience_explicit_flag"].sum())
    experience["share_of_labeled_jobs_pct"] = np.where(
        experience["experience_band"].eq("Not Specified"),
        np.nan,
        (experience["job_count"] / labeled_jobs * 100).round(2),
    )
    experience.to_csv(REPORTS / "experience_distribution.csv", index=False)

    salary_values = jobs.loc[jobs["salary_analysis_eligible"], "salary_midpoint"]
    pd.DataFrame([_salary_summary(salary_values)]).to_csv(
        REPORTS / "salary_summary.csv", index=False
    )
    _group_salary(jobs, "role_family").to_csv(
        REPORTS / "salary_by_role.csv", index=False
    )
    _group_salary(jobs, "specific_city").rename(
        columns={"specific_city": "city"}
    ).to_csv(REPORTS / "salary_by_city.csv", index=False)
    _group_salary(jobs, "experience_band").to_csv(
        REPORTS / "salary_by_experience.csv", index=False
    )

    skill_salary = (
        skills.loc[skills["salary_analysis_eligible"]]
        .groupby(["skill", "skill_category"])["salary_midpoint"]
        .agg(salary_n="size", median_salary="median", mean_salary="mean")
        .reset_index()
    )
    overall_median = salary_values.median()
    skill_salary["median_difference_vs_overall_pct"] = (
        (skill_salary["median_salary"] / overall_median - 1) * 100
    ).round(2)
    skill_salary.loc[skill_salary["salary_n"] >= 5].sort_values(
        "salary_n", ascending=False
    ).to_csv(REPORTS / "skill_salary_summary.csv", index=False)
    skill_salary.sort_values("salary_n", ascending=False).to_csv(
        REPORTS / "skill_salary_associations.csv", index=False
    )

    observed = jobs.loc[jobs["is_posting_date_observed"]].copy()
    recent = observed.loc[observed["is_recent_90d"]]
    prior = observed.loc[~observed["is_recent_90d"]]
    pd.DataFrame(
        [
            {
                "period": "Pre-90-day period",
                "min": prior["posted_date"].min(),
                "max": prior["posted_date"].max(),
                "count": len(prior),
            },
            {
                "period": "Recent 90 days",
                "min": recent["posted_date"].min(),
                "max": recent["posted_date"].max(),
                "count": len(recent),
            },
        ]
    ).to_csv(REPORTS / "recent_period_date_ranges.csv", index=False)
    for frame, name in [(recent, "Recent 90 days"), (prior, "Pre-90-day period")]:
        rows = (
            frame["role_family"]
            .value_counts()
            .rename_axis("role_family")
            .reset_index(name="job_count")
        )
        rows.insert(0, "period", name)
        rows["share_pct"] = (rows["job_count"] / len(frame) * 100).round(2)
        rows.to_csv(
            REPORTS
            / (
                "recent_role_mix.csv"
                if name.startswith("Recent")
                else "pre_role_mix.csv"
            ),
            index=False,
        )
    recent_role = recent["role_family"].value_counts(normalize=True) * 100
    prior_role = prior["role_family"].value_counts(normalize=True) * 100
    shift = pd.DataFrame(
        {"pre_share_pct": prior_role, "recent_share_pct": recent_role}
    ).fillna(0)
    shift["change_pp"] = shift["recent_share_pct"] - shift["pre_share_pct"]
    shift.rename_axis("role_family").reset_index().sort_values(
        "change_pp", ascending=False
    ).to_csv(REPORTS / "recent_role_shift_summary.csv", index=False)

    recent_ids = set(recent["job_id"])
    prior_ids = set(prior["job_id"])
    for ids, name, denominator in [
        (recent_ids, "Recent 90 days", len(recent_ids)),
        (prior_ids, "Pre-90-day period", len(prior_ids)),
    ]:
        rows = (
            skills.loc[skills["job_id"].isin(ids)]
            .groupby(["skill", "skill_category"])["job_id"]
            .nunique()
            .reset_index(name="skill_jobs")
        )
        rows.insert(0, "period", name)
        rows["share_pct"] = (rows["skill_jobs"] / denominator * 100).round(2)
        rows.to_csv(
            REPORTS
            / (
                "recent_skill_mix.csv"
                if name.startswith("Recent")
                else "pre_skill_mix.csv"
            ),
            index=False,
        )

    complete_observed = observed.loc[observed["is_complete_week"]].copy()
    weekly = (
        complete_observed.groupby("week_start")
        .agg(
            weekly_jobs=("job_id", "nunique"),
            hiring_companies=("company_name", "nunique"),
        )
        .reset_index()
    )
    weekly.to_csv(REPORTS / "weekly_hiring_trend.csv", index=False)
    observed_skills = skills.merge(
        complete_observed[["job_id", "week_start"]], on="job_id", how="inner"
    )
    top_skills = skill_counts.head(10).index
    weekly_skill = (
        observed_skills.loc[observed_skills["skill"].isin(top_skills)]
        .groupby(["week_start", "skill"])["job_id"]
        .nunique()
        .reset_index(name="skill_jobs")
    )
    weekly_skill = weekly_skill.merge(
        weekly[["week_start", "weekly_jobs"]], on="week_start", how="left"
    )
    weekly_skill["share_pct"] = (
        weekly_skill["skill_jobs"] / weekly_skill["weekly_jobs"] * 100
    ).round(2)
    weekly_skill.to_csv(REPORTS / "weekly_skill_trend.csv", index=False)
    slopes = []
    week_numbers = (
        pd.to_datetime(weekly["week_start"])
        - pd.to_datetime(weekly["week_start"]).min()
    ).dt.days / 7
    for skill_name in top_skills:
        series = weekly_skill.loc[weekly_skill["skill"] == skill_name].merge(
            weekly[["week_start"]], on="week_start", how="right"
        )
        y = series["share_pct"].fillna(0).to_numpy()
        fit = sm.OLS(y, sm.add_constant(week_numbers.to_numpy(dtype=float))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 2}
        )
        lower, upper = fit.conf_int()[1]
        slopes.append(
            {
                "skill": skill_name,
                "weekly_share_slope_pp": float(fit.params[1]),
                "ci_lower_pp": float(lower),
                "ci_upper_pp": float(upper),
                "direction": (
                    "Positive observed slope" if lower > 0
                    else "Negative observed slope" if upper < 0
                    else "Inconclusive observed slope"
                ),
                "interpretation": "Collection snapshot; not a hiring-growth estimate",
            }
        )
    pd.DataFrame(slopes).sort_values("weekly_share_slope_pp", ascending=False).to_csv(
        REPORTS / "skill_trend_slopes.csv", index=False
    )

    work_mode = (
        jobs["work_mode"]
        .value_counts()
        .rename_axis("work_mode")
        .reset_index(name="job_count")
    )
    _share(work_mode, len(jobs)).to_csv(
        REPORTS / "work_mode_distribution.csv", index=False
    )
    location_scope = (
        jobs["location_scope"]
        .value_counts()
        .rename_axis("location_scope")
        .reset_index(name="job_count")
    )
    _share(location_scope, len(jobs)).to_csv(
        REPORTS / "location_scope_coverage.csv", index=False
    )
    source_skill = (
        jobs.groupby("source_family")
        .agg(
            job_count=("job_id", "nunique"),
            skill_tagged_jobs=("has_extracted_skill", "sum"),
        )
        .reset_index()
    )
    source_skill["coverage_pct"] = (
        source_skill["skill_tagged_jobs"] / source_skill["job_count"] * 100
    ).round(2)
    source_skill.to_csv(REPORTS / "skill_coverage_report.csv", index=False)

    pairs: list[tuple[str, str]] = []
    for _, group in skills.groupby("job_id")["skill"]:
        pairs.extend(itertools.combinations(sorted(set(group)), 2))
    pair_table = (
        pd.Series(pairs)
        .value_counts()
        .rename("pair_jobs")
        .rename_axis("pair")
        .reset_index()
    )
    pair_table[["skill_1", "skill_2"]] = pd.DataFrame(
        pair_table["pair"].tolist(), index=pair_table.index
    )
    pair_table["pair_share_of_skill_tagged_jobs_pct"] = (
        pair_table["pair_jobs"] / jobs["has_extracted_skill"].sum() * 100
    ).round(2)
    pair_table.drop(columns="pair").to_csv(
        REPORTS / "skill_pair_summary.csv", index=False
    )

    build_salary_skill_evidence(jobs, skills)
    build_source_period_skill_summary(jobs, skills)

    sql_ids = set(skills.loc[skills["skill"] == "SQL", "job_id"])
    sql_salary = jobs.loc[
        jobs["salary_analysis_eligible"] & jobs["job_id"].isin(sql_ids),
        "salary_midpoint",
    ]
    other_skills_salary = jobs.loc[
        jobs["salary_analysis_eligible"] & ~jobs["job_id"].isin(sql_ids)
        & jobs["has_extracted_skill"],
        "salary_midpoint",
    ]
    unknown_skills_salary = jobs.loc[
        jobs["salary_analysis_eligible"] & ~jobs["has_extracted_skill"],
        "salary_midpoint",
    ]
    (REPORTS / "final_findings.txt").write_text(
        "Data Analyst Job Market Intelligence: Skill, Experience & Salary Analytics — India\n"
        "==================================================================================\n\n"
        f"Analytical vacancies: {len(jobs):,}\nJob-skill rows: {len(skills):,}\nUnique skills: {skills['skill'].nunique():,}\n"
        f"Skill extraction coverage: {jobs['has_extracted_skill'].mean() * 100:.2f}%\n"
        f"Experience extraction coverage: {jobs['experience_explicit_flag'].mean() * 100:.2f}%\n"
        f"Salary analysis coverage: {jobs['salary_analysis_eligible'].mean() * 100:.2f}%\n\n"
        f"Top role family: Data Analyst ({int((jobs['role_family'] == 'Data Analyst').sum()):,} postings)\n"
        f"Top skill: SQL ({int((skills['skill'] == 'SQL').groupby(skills['job_id']).any().sum()):,} postings)\n"
        f"Top specific city: Bengaluru ({int((jobs['specific_city'] == 'Bengaluru').sum()):,} postings)\n\n"
        f"Salary observations: {len(salary_values):,}\nSalary median: ₹{salary_values.median() / 100_000:.2f}L\n"
        f"Salary mean: ₹{salary_values.mean() / 100_000:.2f}L\nSalary minimum: ₹{salary_values.min() / 100_000:.2f}L\nSalary maximum: ₹{salary_values.max() / 100_000:.2f}L\n\n"
        f"SQL-detected salary observations: {len(sql_salary):,}; median ₹{sql_salary.median()/100_000:.2f}L\n"
        f"Other-skill-detected observations: {len(other_skills_salary):,}; median ₹{other_skills_salary.median()/100_000:.2f}L\n"
        f"Unknown-skill observations: {len(unknown_skills_salary):,}; median ₹{unknown_skills_salary.median()/100_000:.2f}L\n"
        "Historical two-group bootstrap comparisons include unknown skills "
        "in the not-SQL-tagged group and are not used as evidence of a SQL salary premium.\n\n"
        "See salary_skill_evidence.csv for the valid three-group split and "
        "salary_regression_summary.txt for a cautious controlled analysis.\n"
        "Weekly slopes summarize the captured window; they are not a forecast.\n"
        "The salary comparison does not establish that SQL itself raises pay.\n",
        encoding="utf-8",
    )

    _write_figures(jobs, skills)
    print(f"Reports refreshed in: {REPORTS}")
    print("Salary outputs: salary_skill_evidence.csv, salary_regression_summary.txt")


if __name__ == "__main__":
    main()
