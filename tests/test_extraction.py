import sys
import unittest
from datetime import timedelta
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from build_analytical_dataset import (  # noqa: E402
    canonicalize_company_names,
    classify_role_scope,
    classify_seniority,
    deduplicate_cross_source,
    descriptions_match,
    is_explicit_foreign_location,
    normalize_city,
)


ROLE_SCOPE_CASES = [
    ("core data analyst", "Senior Data Analyst", "Build reports", True, "Data Analyst"),
    (
        "core bi analyst",
        "BI Analyst",
        "Business intelligence reporting",
        True,
        "BI / Reporting Analyst",
    ),
    (
        "core reporting analyst",
        "Reporting Analyst",
        "Monthly reporting",
        True,
        "BI / Reporting Analyst",
    ),
    (
        "business analyst with data evidence",
        "Business Analyst",
        "Query data using SQL and build KPI dashboards in Power BI.",
        True,
        "Business Analyst",
    ),
    (
        "business analyst without data evidence",
        "Business Analyst",
        "Gather requirements, facilitate workshops and write user stories.",
        False,
        None,
    ),
    (
        "business analyst with two analytical duties is included",
        "Business Analyst - BPO",
        "Analyze large datasets, validate data quality and provide actionable findings.",
        True,
        "Business Analyst",
    ),
    (
        "technical business analyst is excluded",
        "Technical Business Analyst - Platform Solutions",
        "Write user stories and coordinate platform development teams.",
        False,
        None,
    ),
    (
        "mlops analyst is excluded",
        "Associate MLOps Analyst",
        "Deploy machine learning models and maintain Python services.",
        False,
        None,
    ),
    (
        "product analyst is core title",
        "Associate Product Analyst",
        "Partner with product teams and evaluate customer behavior.",
        True,
        "Product Analyst",
    ),
    (
        "business analytics specialist maps to analytics",
        "Specialist, Business Analytics",
        "Support commercial teams with reporting and insights.",
        True,
        "Analytics Analyst",
    ),
    (
        "reverse financial planning title maps to finance",
        "Analyst Financial Planning & Analysis Technology",
        "Build forecasts, management reporting and data-quality checks.",
        True,
        "Pricing / Revenue / Finance Analytics",
    ),
    (
        "operations analyst with data evidence",
        "Operations Analyst",
        "Analyse operational KPIs, forecast demand and develop Tableau dashboards.",
        True,
        "Operations / Supply Chain Analytics",
    ),
    (
        "operations analyst without data evidence",
        "Operations Analyst",
        "Coordinate schedules and resolve customer tickets.",
        False,
        None,
    ),
    (
        "financial analyst requires evidence",
        "Financial Analyst",
        "Build Excel forecasts, Power BI dashboards and management reporting.",
        True,
        "Pricing / Revenue / Finance Analytics",
    ),
    (
        "generic analyst requires strong evidence",
        "Senior Analyst",
        "Use SQL and Python for data analysis and publish KPI dashboards in Tableau.",
        True,
        "General Analytics Analyst",
    ),
    (
        "generic analyst without evidence",
        "Senior Analyst",
        "Support daily business activities.",
        False,
        None,
    ),
    (
        "workday analyst is excluded",
        "Workday Analyst",
        "Build Workday reports and maintain HR systems.",
        False,
        None,
    ),
    (
        "security analyst is excluded",
        "Information Security Analyst",
        "Monitor security dashboards and analyse incidents using SQL.",
        False,
        None,
    ),
    (
        "analytics engineer is excluded",
        "Analytics Engineer",
        "Build dbt models in Snowflake and create BI datasets.",
        False,
        None,
    ),
    (
        "data scientist with analytics word is excluded",
        "Data Scientist - Python and Deterministic Analytics",
        "Use SQL and Python for data analysis and dashboards.",
        False,
        None,
    ),
    (
        "application development analyst is excluded",
        "Application Development Senior Analyst",
        "Use SQL and Python to support application development.",
        False,
        None,
    ),
    (
        "it analyst is excluded",
        "Sr IT Analyst",
        "Build dashboards and query operational data using SQL.",
        False,
        None,
    ),
    (
        "application development before bi is excluded",
        "Analyst-Application Development-Business Intelligence",
        "Develop enterprise applications and BI components using SQL.",
        False,
        None,
    ),
    (
        "data engineering analytics title is excluded",
        "Data Engineering II - Data and Analytics - In House Engineering",
        "Build data pipelines using SQL, Python and cloud platforms.",
        False,
        None,
    ),
    (
        "sap analytics specialist is excluded",
        "SAP Business Analytics Support Specialist",
        "Configure SAP Analytics Cloud reports and dashboards.",
        False,
        None,
    ),
    (
        "sap analytics title without analyst is excluded",
        "Senior SAP CDS Analytics - SAC, CDS",
        "Build SAP analytics reports and dashboards.",
        False,
        None,
    ),
    (
        "incident response analyst is excluded",
        "Incident Response Analyst",
        "Investigate security incidents using SQL and dashboards.",
        False,
        None,
    ),
    (
        "data solutions analyst maps to data",
        "Data Solutions Analyst",
        "Analyze datasets using SQL and publish KPI dashboards.",
        True,
        "Data Analyst",
    ),
    (
        "product operations analyst maps to product",
        "Analyst, Product Operations",
        "Analyze product KPIs using SQL and Tableau.",
        True,
        "Product Analyst",
    ),
    (
        "data management analyst maps to governance",
        "Data and Information Management Analyst",
        "Monitor data quality, governance metrics and SQL validation rules.",
        True,
        "Data Quality / Governance Analyst",
    ),
    (
        "sourcing rate analyst maps to finance",
        "Sourcing Rate Analyst",
        "Analyze supplier rates in Excel and Power BI and produce forecasts.",
        True,
        "Pricing / Revenue / Finance Analytics",
    ),
    (
        "data strategy analyst maps to strategy",
        "Senior Analyst, AI and Data Strategy",
        "Analyze strategic KPIs using SQL and develop management dashboards.",
        True,
        "Strategy / Performance Analytics",
    ),
    (
        "data surveillance analyst maps to risk",
        "Data Surveillance Analyst",
        "Use SQL and statistical analysis to identify anomalous risk patterns.",
        True,
        "Risk / Fraud Analytics",
    ),
    (
        "qa engineer analytics title is excluded",
        "Sr Analyst Quality - QA Testing Engineer",
        "Use SQL to test analytics pipelines and dashboards.",
        False,
        None,
    ),
    (
        "analytics administrator is excluded",
        "Support Operations Senior Data Analytics Administrator",
        "Administer reporting platforms and support users with SQL queries.",
        False,
        None,
    ),
    (
        "generic analytics developer is excluded",
        "Data Analytics Python Developer",
        "Develop Python services and SQL integrations for analytics products.",
        False,
        None,
    ),
    (
        "power bi developer analyst hybrid is included",
        "Junior Power BI Developer/Analyst",
        "Analyze KPI trends and build Power BI dashboards using SQL.",
        True,
        "BI / Reporting Analyst",
    ),
    (
        "dashboard analyst bi developer hybrid is included",
        "Senior Dashboard Analyst/BI Developer",
        "Analyze business metrics and deliver dashboards using SQL and Power BI.",
        True,
        "BI / Reporting Analyst",
    ),
    (
        "fp and a normalized title maps to finance",
        "Senior FP&A Analyst",
        "Build Excel forecasts, management reporting and Power BI dashboards.",
        True,
        "Pricing / Revenue / Finance Analytics",
    ),
    (
        "business intelligence after analyst maps to bi",
        "Senior Analyst, Business Intelligence",
        "Build SQL datasets and Power BI dashboards.",
        True,
        "BI / Reporting Analyst",
    ),
    (
        "business analytics senior analyst maps to analytics",
        "Business Analytics Senior Analyst",
        "Use SQL and Python for analysis and reporting.",
        True,
        "Analytics Analyst",
    ),
    (
        "accounting operations analyst is excluded",
        "Record to Report Ops Senior Analyst",
        "Prepare journal entries and account reconciliations.",
        False,
        None,
    ),
    (
        "data analytics manager is separate",
        "Data Analytics Manager",
        "Lead SQL analysis and Power BI dashboard delivery.",
        True,
        "Analytics Leadership",
    ),
    (
        "data science analyst is excluded",
        "Senior Analyst - Data Science and Analytics",
        "Use SQL, Python and dashboards for predictive modelling.",
        False,
        None,
    ),
    (
        "analytics product manager is excluded",
        "Product Manager - Business Intelligence and Analytics",
        "Use SQL and dashboards to define product strategy and metrics.",
        False,
        None,
    ),
    (
        "data analytics project manager is excluded",
        "Project Manager - Data and Analytics",
        "Manage SQL reporting and data-platform delivery projects.",
        False,
        None,
    ),
    (
        "analytics architect is excluded",
        "Director, Enterprise Data and Analytics Architect",
        "Design enterprise data platforms and analytics architecture.",
        False,
        None,
    ),
    (
        "accounting analyst is excluded",
        "Asset Accounting Analyst",
        "Use Excel and Power BI for accounting reports and reconciliation.",
        False,
        None,
    ),
    (
        "manager analytics maps to leadership",
        "Manager, Analytics",
        "Lead SQL analysis and KPI dashboard delivery using Power BI.",
        True,
        "Analytics Leadership",
    ),
    (
        "programmer analyst is excluded",
        "Principal Programmer Analyst",
        "Use SQL and Python to develop reporting applications.",
        False,
        None,
    ),
    (
        "information systems analyst is excluded",
        "Specialist IS Analyst",
        "Maintain information systems and produce SQL reports.",
        False,
        None,
    ),
    (
        "it sourcing analyst is excluded",
        "Senior Analyst, IT Sourcing and Vendor Management",
        "Analyze vendor metrics using Excel and Power BI dashboards.",
        False,
        None,
    ),
]


class RoleScopeTests(unittest.TestCase):
    def test_role_scope_examples(self):
        for case, title, description, included, family in ROLE_SCOPE_CASES:
            with self.subTest(case=case):
                result = classify_role_scope(title, description)
                self.assertEqual(result["role_in_scope"], included, title)
                if family is not None:
                    self.assertEqual(result["role_family"], family, title)


class LocationNormalizationTests(unittest.TestCase):
    def test_kolkatta_maps_to_kolkata(self):
        self.assertEqual(normalize_city("Kolkatta, West Bengal"), "Kolkata")

    def test_indianapolis_is_explicitly_foreign(self):
        self.assertTrue(is_explicit_foreign_location("Indianapolis, IN, USA"))

    def test_indian_city_is_not_explicitly_foreign(self):
        self.assertFalse(is_explicit_foreign_location("Pune, Maharashtra, India"))

    def test_work_from_home_maps_to_remote_india(self):
        self.assertEqual(normalize_city("work from home"), "Remote - India")


class FeatureTests(unittest.TestCase):
    def test_seniority_from_title(self):
        self.assertEqual(classify_seniority("Lead Data Analyst"), "Lead / Principal")
        self.assertEqual(classify_seniority("Junior BI Analyst"), "Junior")

    def test_description_containment_matches_cross_source_copy(self):
        snippet = (
            "The analyst will use SQL and Power BI to prepare dashboards for leaders."
        )
        full = snippet + " The role also partners with finance and operations teams."
        matched, score = descriptions_match(snippet * 3, full + snippet * 2)
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 0.72)

    def test_cross_source_dedup_uses_job_id_as_final_tie_break(self):
        timestamp = pd.Timestamp("2026-08-29T08:00:00Z")
        description = (
            "The analyst uses SQL and Power BI to prepare KPI dashboards. " * 5
        )
        frame = pd.DataFrame(
            [
                {
                    "job_id": "source-b:200",
                    "api_source": "Source B",
                    "title": "Data Analyst",
                    "company_name": "Example Company",
                    "location_name": "Bengaluru",
                    "city": "Bengaluru",
                    "description": description,
                    "description_type": "full",
                    "created_at": timestamp,
                    "collected_at": timestamp,
                    "collected_at_utc": timestamp.isoformat(),
                    "is_posting_date_observed": True,
                },
                {
                    "job_id": "source-a:100",
                    "api_source": "Source A",
                    "title": "Data Analyst",
                    "company_name": "Example Company",
                    "location_name": "Bengaluru",
                    "city": "Bengaluru",
                    "description": description,
                    "description_type": "full",
                    "created_at": timestamp,
                    "collected_at": timestamp,
                    "collected_at_utc": timestamp.isoformat(),
                    "is_posting_date_observed": True,
                },
            ]
        )

        clean, audit = deduplicate_cross_source(frame)

        self.assertEqual(clean["job_id"].tolist(), ["source-a:100"])
        self.assertEqual(audit["retained_job_id"].tolist(), ["source-a:100"])


class DataQualityRegressionTests(unittest.TestCase):
    """Safeguard employer, location, and duplicate normalization rules."""

    def test_company_aliases(self):
        names = pd.Series([
            "Citi", "Citigroup", "Citigroup Pvt Ltd",
            "Acme Pvt Ltd", "Acme", "Acme Analytics",
        ])
        self.assertEqual(
            canonicalize_company_names(names).tolist(),
            [
                "Citigroup", "Citigroup", "Citigroup",
                "Acme", "Acme", "Acme Analytics",
            ],
        )

    def test_city_normalization(self):
        cases = {
            "Navi Mumbai, Maharashtra": "Navi Mumbai",
            "Maharashtra, India": "City Not Specified",
            "Hyderabad, Telangana": "Hyderabad",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_city(raw), expected)

    @staticmethod
    def duplicate_jobs():
        posted = pd.Timestamp("2026-08-29T08:00:00Z")
        description = (
            "Build and maintain SQL datasets and Power BI dashboards "
            "for analytics stakeholders. "
        ) * 4
        common = {
            "api_source": "Adzuna",
            "title": "Data Analyst",
            "company_name": "Acme",
            "location_name": "Hyderabad",
            "city": "Hyderabad",
            "description": description,
            "description_type": "full",
            "collected_at": posted,
            "is_posting_date_observed": True,
        }
        return pd.DataFrame([
            {**common, "job_id": "A:001", "created_at": posted},
            {**common, "job_id": "A:002", "created_at": posted},
        ])

    def test_within_source_duplicates_removed(self):
        clean, audit = deduplicate_cross_source(self.duplicate_jobs())
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.iloc[0]["removed_source"], "Adzuna")
        self.assertEqual(audit.iloc[0]["retained_source"], "Adzuna")

    def test_different_posting_dates_preserved(self):
        jobs = self.duplicate_jobs()
        jobs.loc[1, "created_at"] = (
            jobs.loc[1, "created_at"] + timedelta(days=3)
        )
        clean, audit = deduplicate_cross_source(jobs)
        self.assertEqual(len(clean), 2)
        self.assertEqual(len(audit), 0)


if __name__ == "__main__":
    unittest.main()
