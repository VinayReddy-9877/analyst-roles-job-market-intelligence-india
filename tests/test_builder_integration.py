import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_analytical_dataset as builder  # noqa: E402


class BuilderIntegrationTests(unittest.TestCase):
    def make_row(self, job_id, title, description, **overrides):
        row = {
            "job_id": job_id,
            "source_job_id": job_id.split(":", 1)[-1],
            "api_source": "Freehire",
            "source": "Freehire API / greenhouse",
            "source_provider": "greenhouse",
            "snapshot_id": "2026-08-29",
            "collected_at_utc": "2026-08-29T12:00:00Z",
            "title": title,
            "company_name": "Example Ltd",
            "location_name": "Pune, India",
            "country_validation": "confirmed",
            "description": description,
            "description_type": "full",
            "created": "2026-08-20T10:00:00Z",
            "redirect_url": f"https://example.com/{job_id}",
            "workplace_type": None,
            "experience_min_years": None,
            "experience_max_years": None,
            "seniority_raw": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "salary_is_predicted": False,
            "contract_type": None,
            "contract_time": None,
        }
        row.update(overrides)
        return row

    def test_builder_filters_maps_and_deduplicates(self):
        repeated = (
            "Use SQL and Power BI to analyse business data and build KPI dashboards. "
            * 3
        ).strip()
        rows = [
            self.make_row("freehire:1", "Data Analyst", repeated),
            self.make_row(
                "freehire:2",
                "Business Analyst",
                "Use SQL to analyse data and create KPI dashboards in Tableau.",
                company_name="Business Co",
                created="2026-08-29T14:00:00Z",
            ),
            self.make_row(
                "freehire:3",
                "Application Support Analyst",
                "Support dashboards and SQL applications.",
                company_name="Support Co",
            ),
            self.make_row(
                "freehire:4",
                "Data Analyst",
                repeated,
                company_name="Ambiguous Co",
                country_validation="ambiguous",
            ),
            self.make_row(
                "adzuna:5",
                "Data Analyst",
                repeated,
                api_source="Adzuna",
                source="Adzuna API",
                source_provider="Adzuna",
                description_type="snippet",
            ),
            self.make_row(
                "jooble:6",
                "Reporting Analyst",
                "Create SQL reports and Power BI dashboards for operational KPIs.",
                company_name="Reporting Co",
                api_source="Jooble",
                source="Jooble API / example.com",
                source_provider="example.com",
                posting_date_basis="source_updated_at_proxy",
                created="2026-07-15T00:00:00Z",
                description_type="snippet",
            ),
            self.make_row(
                "jsearch:7",
                "Data Quality Analyst",
                "Use SQL and Python to monitor data quality and governance controls.",
                company_name="Quality Data Co",
                api_source="JSearch",
                source="JSearch API / LinkedIn",
                source_provider="LinkedIn",
                posting_date_basis="source_posted_at",
                created="2026-08-18T00:00:00Z",
                description_type="full",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw = root / "raw.csv"
            pd.DataFrame(rows).to_csv(raw, index=False)

            replacements = {
                "RAW_FILE": raw,
                "CLEAN_FILE": root / "processed" / "jobs.csv",
                "SKILLS_FILE": root / "processed" / "skills.csv",
                "EXCLUDED_FILE": root / "interim" / "excluded.csv",
                "DEDUPE_AUDIT_FILE": root / "interim" / "dedupe.csv",
                "PROCESSED_DIR": root / "processed",
                "INTERIM_DIR": root / "interim",
                "REPORT_DIR": root / "reports",
                "REPORT_FILE": root / "reports" / "report.txt",
                "ROLE_AUDIT_FILE": root / "reports" / "roles.csv",
                "SKILL_COVERAGE_FILE": root / "reports" / "skills_report.csv",
                "EXCLUSION_SUMMARY_FILE": root / "reports" / "exclusions.csv",
                "TAXONOMY_SAMPLE_FILE": root / "reports" / "taxonomy_sample.csv",
            }
            original = {name: getattr(builder, name) for name in replacements}
            try:
                for name, value in replacements.items():
                    setattr(builder, name, value)
                builder.main()
            finally:
                for name, value in original.items():
                    setattr(builder, name, value)

            clean = pd.read_csv(replacements["CLEAN_FILE"])
            excluded = pd.read_csv(replacements["EXCLUDED_FILE"])
            dedupe = pd.read_csv(replacements["DEDUPE_AUDIT_FILE"])
            exclusion_summary = pd.read_csv(replacements["EXCLUSION_SUMMARY_FILE"])
            taxonomy_sample = pd.read_csv(replacements["TAXONOMY_SAMPLE_FILE"])

            self.assertEqual(len(clean), 4)
            self.assertEqual(clean["job_id"].nunique(), 4)
            self.assertEqual(
                set(clean["role_family"]),
                {
                    "Data Analyst",
                    "Business Analyst",
                    "BI / Reporting Analyst",
                    "Data Quality / Governance Analyst",
                },
            )
            timestamp_issue = clean.loc[clean["job_id"].eq("freehire:2")].iloc[0]
            self.assertTrue(timestamp_issue["posting_timestamp_inconsistency_flag"])
            self.assertEqual(timestamp_issue["posting_age_at_snapshot_days"], 0)
            proxy_date = clean.loc[clean["job_id"].eq("jooble:6")].iloc[0]
            self.assertFalse(proxy_date["is_posting_date_observed"])
            self.assertTrue(pd.isna(proxy_date["posting_age_at_snapshot_days"]))
            observed_date = clean.loc[clean["job_id"].eq("jsearch:7")].iloc[0]
            self.assertTrue(observed_date["is_posting_date_observed"])
            self.assertEqual(len(excluded), 2)
            self.assertEqual(len(dedupe), 1)
            self.assertIn("Application Support Analyst", set(excluded["title"]))
            self.assertEqual(exclusion_summary["row_count"].sum(), 2)
            self.assertEqual(len(taxonomy_sample), 5)
            self.assertEqual(int(taxonomy_sample["model_in_scope"].sum()), 4)


if __name__ == "__main__":
    unittest.main()
