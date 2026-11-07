"""
Data Analyst Job Market Intelligence: Skill, Experience & Salary Analytics — India

Analytical dataset builder.

Input
-----
data/raw/job_postings_raw_20260829.csv

Outputs
-------
data/processed/job_postings_clean.csv
data/processed/job_skills_bridge.csv
reports/analytical_dataset_report.txt
reports/role_scope_audit.csv
reports/skill_coverage_report.csv
reports/exclusion_reason_summary.csv
reports/taxonomy_validation_sample.csv
data/interim/excluded_postings.csv
data/interim/deduplication_audit.csv
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import hashlib
import re
import unicodedata
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd

from config import (
    CLEAN_FILE,
    DEDUPE_AUDIT_FILE,
    EXCLUSION_SUMMARY_FILE,
    EXCLUDED_FILE,
    INTERIM_DIR,
    PROCESSED_DIR,
    PROJECT_ROOT,
    RAW_FILE,
    REPORT_DIR,
    SKILLS_FILE,
    SNAPSHOT_ID,
    TAXONOMY_SAMPLE_FILE,
    WINDOW_END,
    WINDOW_START,
)

REPORT_FILE = REPORT_DIR / "analytical_dataset_report.txt"
ROLE_AUDIT_FILE = REPORT_DIR / "role_scope_audit.csv"
SKILL_COVERAGE_FILE = REPORT_DIR / "skill_coverage_report.csv"

# Auditable employer-group aliases; not necessarily identical legal entities.
# Keep Morgan Stanley, CITIC, citicclsa and JP Morgan Services India separate.
COMPANY_ALIASES = {
    "citi": "Citigroup",
    "citigroup": "Citigroup",
    "jpmorganchase": "JPMorgan Chase",
    "jpmorganchaseco": "JPMorgan Chase",
    "jpmorganco": "JPMorgan Chase",
    "amgen": "Amgen",
    "amgentechnology": "Amgen",
}

STATE_ONLY_LOCATIONS = {
    "andhra pradesh", "bihar", "chhattisgarh", "delhi ncr", "goa", "gujarat",
    "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "odisha", "orissa", "punjab",
    "rajasthan", "tamil nadu", "telangana", "uttar pradesh", "uttarakhand",
    "west bengal", "india", "new delhi ncr",
}

NON_PRODUCTION_COMPANY_NAMES = {
    "testhiring",
    "test",
    "demo",
    "sample company",
    "xyz company",
    "abc company",
    "dummy",
}

CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "mumbai": "Mumbai",
    "navi mumbai": "Navi Mumbai",
    "thane": "Thane",
    "chennai": "Chennai",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "noida": "Noida",
    "new delhi": "Delhi",
    "delhi": "Delhi",
    "kolkata": "Kolkata",
    "kolkatta": "Kolkata",
    "calcutta": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "jaipur": "Jaipur",
    "chandigarh": "Chandigarh",
    "coimbatore": "Coimbatore",
    "indore": "Indore",
    "vadodara": "Vadodara",
    "baroda": "Vadodara",
    "bhubaneswar": "Bhubaneswar",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
    "lucknow": "Lucknow",
    "thiruvananthapuram": "Thiruvananthapuram",
    "trivandrum": "Thiruvananthapuram",
}


STATE_BY_CITY = {
    "Bengaluru": "Karnataka",
    "Hyderabad": "Telangana",
    "Pune": "Maharashtra",
    "Mumbai": "Maharashtra",
    "Navi Mumbai": "Maharashtra",
    "Thane": "Maharashtra",
    "Chennai": "Tamil Nadu",
    "Gurugram": "Haryana",
    "Noida": "Uttar Pradesh",
    "Delhi": "Delhi",
    "Kolkata": "West Bengal",
    "Ahmedabad": "Gujarat",
    "Kochi": "Kerala",
    "Jaipur": "Rajasthan",
    "Chandigarh": "Chandigarh",
    "Coimbatore": "Tamil Nadu",
    "Indore": "Madhya Pradesh",
    "Vadodara": "Gujarat",
    "Bhubaneswar": "Odisha",
    "Visakhapatnam": "Andhra Pradesh",
    "Lucknow": "Uttar Pradesh",
    "Thiruvananthapuram": "Kerala",
}


SKILL_RULES = {
    "SQL": [r"\bsql\b"],
    "Python": [r"\bpython\b"],
    "Excel": [r"\bmicrosoft excel\b", r"\bms excel\b", r"\bexcel\b"],
    "Power BI": [r"\bpower\s*bi\b", r"\bpowerbi\b"],
    "Tableau": [r"\btableau\b"],
    "R": [
        r"(?<![a-z0-9])r programming(?![a-z0-9])",
        r"(?<![a-z0-9])r language(?![a-z0-9])",
    ],
    "DAX": [r"\bdax\b"],
    "Power Query": [r"\bpower query\b"],
    "PostgreSQL": [r"\bpostgresql\b", r"\bpostgres\b"],
    "MySQL": [r"\bmysql\b"],
    "Oracle": [r"\boracle sql\b", r"\boracle database\b", r"\boracle db\b"],
    "SQL Server": [r"\bsql server\b", r"\bmssql\b"],
    "BigQuery": [r"\bbigquery\b", r"\bgoogle big query\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "Redshift": [r"\bredshift\b"],
    "Databricks": [r"\bdatabricks\b"],
    "Azure": [r"\bmicrosoft azure\b", r"\bazure\b"],
    "AWS": [r"\bamazon web services\b", r"\baws\b"],
    "GCP": [r"\bgoogle cloud platform\b", r"\bgcp\b"],
    "Looker": [r"\blooker\b"],
    "Qlik": [r"\bqlik sense\b", r"\bqlikview\b", r"\bqlik\b"],
    "Alteryx": [r"\balteryx\b"],
    "dbt": [r"\bdbt\b"],
    "Airflow": [r"\bapache airflow\b", r"\bairflow\b"],
    "Spark": [r"\bapache spark\b", r"\bpyspark\b", r"\bspark\b"],
    "Hadoop": [r"\bhadoop\b"],
    "ETL": [r"\betl\b"],
    "ELT": [r"\belt\b"],
    "Data Modeling": [
        r"\bdata modelling\b",
        r"\bdata modeling\b",
        r"\bdimensional modeling\b",
        r"\bdimensional modelling\b",
    ],
    "Data Warehousing": [r"\bdata warehouse\b", r"\bdata warehousing\b"],
    "Statistics": [
        r"\bstatistics\b",
        r"\bstatistical analysis\b",
        r"\bstatistical modelling\b",
        r"\bstatistical modeling\b",
    ],
    "A/B Testing": [r"\ba/?b testing\b", r"\bab testing\b", r"\bexperimentation\b"],
    "Regression": [r"\bregression\b"],
    "Forecasting": [r"\bforecasting\b"],
    "Machine Learning": [r"\bmachine learning\b", r"\bml models?\b"],
    "Pandas": [r"\bpandas\b"],
    "NumPy": [r"\bnumpy\b"],
    "SciPy": [r"\bscipy\b"],
    "Git": [r"\bgit\b", r"\bgithub\b", r"\bgitlab\b"],
    "Jira": [r"\bjira\b"],
    "SSIS": [r"\bssis\b"],
    "SAP": [r"\bsap\b"],
    "SAS": [r"\bsas\b"],
    "SPSS": [r"\bspss\b"],
}


SKILL_CATEGORIES = {
    "SQL": "Database / Query",
    "Python": "Programming",
    "Excel": "Spreadsheet",
    "Power BI": "BI / Visualization",
    "Tableau": "BI / Visualization",
    "R": "Programming",
    "DAX": "BI / Visualization",
    "Power Query": "BI / Visualization",
    "PostgreSQL": "Database / Query",
    "MySQL": "Database / Query",
    "Oracle": "Database / Query",
    "SQL Server": "Database / Query",
    "BigQuery": "Cloud / Warehouse",
    "Snowflake": "Cloud / Warehouse",
    "Redshift": "Cloud / Warehouse",
    "Databricks": "Data Engineering",
    "Azure": "Cloud",
    "AWS": "Cloud",
    "GCP": "Cloud",
    "Looker": "BI / Visualization",
    "Qlik": "BI / Visualization",
    "Alteryx": "Analytics Tool",
    "dbt": "Data Engineering",
    "Airflow": "Data Engineering",
    "Spark": "Data Engineering",
    "Hadoop": "Data Engineering",
    "ETL": "Data Engineering",
    "ELT": "Data Engineering",
    "Data Modeling": "Data Engineering",
    "Data Warehousing": "Data Engineering",
    "Statistics": "Statistics / Analytics",
    "A/B Testing": "Statistics / Analytics",
    "Regression": "Statistics / Analytics",
    "Forecasting": "Statistics / Analytics",
    "Machine Learning": "Machine Learning",
    "Pandas": "Programming",
    "NumPy": "Programming",
    "SciPy": "Programming",
    "Git": "Developer Tool",
    "Jira": "Collaboration Tool",
    "SSIS": "Data Engineering",
    "SAP": "Enterprise Tool",
    "SAS": "Statistics / Analytics",
    "SPSS": "Statistics / Analytics",
}


EXPERIENCE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:years?|yrs?)\b", flags=re.I),
    re.compile(
        r"\b(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d{1,2})\+?\s*(?:years?|yrs?)\b",
        flags=re.I,
    ),
    re.compile(r"\b(\d{1,2})\+\s*(?:years?|yrs?)\b", flags=re.I),
    re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b", flags=re.I),
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


def normalized_text(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def company_key(value: Any) -> str:
    text = clean_text(value)
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    text = re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()
    # Strip only legal suffixes; keep meaningful qualifiers such as India.
    text = re.sub(
        r"(?:\s+(?:private|pvt|limited|ltd|inc|llp|llc|corp|corporation))+\s*$",
        "",
        text,
    )
    key = re.sub(r"\s+", "", text)
    # Apply an explicit, auditable reviewed-alias map, not fuzzy grouping.
    return re.sub(r"[^a-z0-9]+", "", COMPANY_ALIASES.get(key, key).lower())


def canonicalize_company_names(series: pd.Series) -> pd.Series:
    cleaned = series.map(clean_text).replace("", "Unknown Company")

    counts = cleaned.value_counts(dropna=False)

    groups: dict[str, list[tuple[str, int]]] = {}

    for name, count in counts.items():
        key = company_key(name)
        groups.setdefault(key, []).append((str(name), int(count)))

    display_by_name: dict[str, str] = {}

    for variants in groups.values():
        readable = [
            item
            for item in variants
            if not (
                any(ch.isalpha() for ch in item[0])
                and all(not ch.isalpha() or ch.islower() for ch in item[0])
            )
        ]

        pool = readable if readable else variants

        display_name = sorted(pool, key=lambda item: (-item[1], item[0]))[0][0]
        alias = COMPANY_ALIASES.get(company_key(display_name))
        if alias:
            display_name = alias

        for name, _ in variants:
            display_by_name[name] = display_name

    return cleaned.map(display_by_name)


def boolean_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except Exception:
        pass

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) == 1.0

    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def source_family(value: Any) -> str:
    text = clean_text(value).lower()

    if "adzuna" in text:
        return "Adzuna"

    if text.startswith("freehire"):
        return "Freehire"

    if "jooble" in text:
        return "Jooble"

    if "jsearch" in text:
        return "JSearch"

    return "Other"


def source_provider(value: Any) -> str:
    text = clean_text(value)

    if not text:
        return "Unknown"

    if "/" in text:
        provider = text.split("/", 1)[1].strip()
        return provider.title() if provider else "Unknown"

    if "adzuna" in text.lower():
        return "Adzuna"

    return text


TITLE_EXCLUSION_RULES = [
    (
        "IT, application, or systems support",
        [
            r"\bapplication support analyst\b",
            r"\bit support analyst\b",
            r"\bhelp\s*desk analyst\b",
            r"\bservice desk analyst\b",
            r"\bbusiness systems? analyst\b",
            r"\bsystems? analyst\b",
            r"\bfunctional analyst\b",
            r"\bworkday analyst\b",
            r"\bhris analyst\b",
            r"\bit analyst\b",
            r"\b(?:is|information systems?) analyst\b",
            r"\banalyst\b.*\bit sourcing\b",
            r"\bapplication development .*analyst\b",
            r"\banalyst.*\bapplication development\b",
            r"\bdata development .*analyst\b",
            r"\banalyst.*\bdata development\b",
            r"\btechnical support\b",
            r"\bengineering (?:systems? )?support\b",
            r"\b(?:is|information systems?) bus(?:iness)? sys(?:tems)? analyst\b",
            r"\btechnology analyst\b",
            r"\bit project .*analyst\b",
            r"\btechnical business analyst\b",
            r"\bsap\b.*\b(?:analyst|developer|consultant|specialist|manager|lead)\b",
            r"\b(?:analyst|manager|specialist)\b.*\bsap\b",
            r"\bsap\b",
        ],
    ),
    (
        "Security or compliance",
        [
            r"\b(?:information |cyber )?security analyst\b",
            r"\bsoc analyst\b",
            r"\bcompliance analyst\b",
            r"\blegal analyst\b",
            r"\bincident response analyst\b",
        ],
    ),
    (
        "Software, QA, or data engineering",
        [
            r"\bsoftware (?:engineering )?.*analyst\b",
            r"\bquality assurance analyst\b",
            r"\bqa analyst\b",
            r"\bdata engineering .*analyst\b",
            r"\banalytics engineer\b",
            r"\bdata engineer\b",
            r"\bdata scientist\b",
            r"\bdata science\b",
            r"\bmachine learning (?:engineer|scientist)\b",
            r"\bmlops analyst\b",
            r"\bai analyst\b",
            r"(?<!data )\bquality analyst\b",
            r"\bdata engineering\b",
            r"\bsoftware engineering\b",
            r"\bengineering manager\b",
            r"\bqa\b",
            r"\btesting engineer\b",
            r"\btest analyst\b",
            r"\bprogrammer\b",
            r"\bdeveloper\b",
            r"\badministrator\b",
            r"\barchitect\b",
            r"\bweb application firewall\b",
            r"\bwaf\b",
            r"\bdigital design\b",
            r"\bproduct success analyst\b",
        ],
    ),
    (
        "Accounting operations or specialist finance",
        [
            r"\brecord to report\b",
            r"\bprocure to pay\b",
            r"\border to cash\b",
            r"\bcredit processing analyst\b",
            r"\bclaims analyst\b",
            r"\bunderwriting analyst\b",
            r"\btax analyst\b",
            r"\btax operations\b.*\banalyst\b",
            r"\btreasury analyst\b",
            r"\bcontrollership analyst\b",
            r"\baccounting\b.*\banalyst\b",
            r"\banalyst\b.*\baccounting\b",
        ],
    ),
    (
        "Non-analytics specialist role",
        [
            r"\bcontent analyst\b",
            r"\blaboratory analyst\b",
            r"\bchemical analyst\b",
            r"\bclinical analyst\b",
            r"\brecruitment analyst\b",
            r"\bproduct manager\b",
            r"\bproject manager\b",
        ],
    ),
]

# A small set of explicit hybrid titles is still part of the BI analyst market.
# These are evaluated before the broad developer exclusion above; generic
# software, SQL, SAP and data-engineering developers remain out of scope.
BI_HYBRID_ROLE_PATTERNS = [
    r"\bpower bi developer\s*/\s*analyst\b",
    r"\bdashboard analyst\s*/\s*bi developer\b",
    r"\banalyst\b.*\btableau developer\b",
]

CORE_ROLE_RULES = [
    (
        "Data Analyst",
        [
            r"\bdata analyst\b",
            r"\bdata analytics analyst\b",
            r"\banalyst\s*[-–:]?\s*data analytics\b",
            r"\banalyst\b.*\bdata (?:and )?insights?\b",
            r"\bdata solutions analyst\b",
        ],
    ),
    (
        "BI / Reporting Analyst",
        [
            r"\bbusiness intelligence analyst\b",
            r"\bbi analyst\b",
            r"\breporting analyst\b",
            r"\bmis analyst\b",
            r"\bdata visualization analyst\b",
            r"\bmeasurement (?:and|&) report(?:ing)? analyst\b",
            r"\banalyst.*\bbi\b.*\breporting\b",
            r"\banalyst.*\bbusiness data services\b",
            r"\banalyst\b.*\bvisualization\b",
            r"\bdata measurement (?:and )?reporting\b.*\banalyst\b",
            r"\banalyst\b.*\bbusiness intelligence\b",
        ],
    ),
    (
        "Analytics Analyst",
        [
            r"\banalytics analyst\b",
            r"\banalytics associate\b",
            r"\bprocess analytics\b.*\banalyst\b",
            r"\bdecision sci(?:ence)?\b.*\banalyst\b",
            r"\b(?:business|advanced|data) analytics\b.*\banalyst\b",
            r"\banalyst\b.*\bdata analytics\b",
            r"\banalyst\b.*\bprocess analytics\b",
            r"\bassociate\b.*\bdata analytics\b",
            r"\b(?:specialist|associate)\b.*\bbusiness analytics\b",
        ],
    ),
    (
        "Insights Analyst",
        [
            r"\binsights? analyst\b",
            r"\bcustomer insights? analyst\b",
            r"\banalyst\b.*\b(?:commercial |customer )?insights?\b",
        ],
    ),
    (
        "Data Quality / Governance Analyst",
        [
            r"\bdata quality analyst\b",
            r"\bdata governance analyst\b",
            r"\bdata integrity analyst\b",
            r"\bdata validation analyst\b",
            r"\bdata quality\b.*\banalyst\b",
            r"\banalyst\b.*\bdata quality\b",
            r"\bdata (?:and information )?management analyst\b",
            r"\banalyst\b.*\bdata and process management\b",
        ],
    ),
    ("Product Analyst", [r"\bproduct analyst\b"]),
]

ADJACENT_ROLE_RULES = [
    ("Business Analyst", [r"\bbusiness analyst\b"]),
    (
        "Product Analyst",
        [
            r"\bproduct ops\b.*\b(?:analyst|specialist)\b",
            r"\bproduct (?:operations|management)\b.*\banalyst\b",
            r"\banalyst\b.*\bproduct operations\b",
        ],
    ),
    (
        "Marketing / Customer Analytics",
        [
            r"\bmarketing analyst\b",
            r"\bcampaign .*analyst\b",
            r"\bcustomer analytics analyst\b",
            r"\bweb analyst\b",
            r"\bdigital analyst\b",
        ],
    ),
    (
        "Operations / Supply Chain Analytics",
        [
            r"\boperations analyst\b",
            r"\bsupply chain analyst\b",
            r"\bworkforce analyst\b",
            r"\bprocess analyst\b",
            r"\bprocurement analyst\b",
        ],
    ),
    (
        "Risk / Fraud Analytics",
        [
            r"\brisk analyst\b",
            r"\bfraud analyst\b",
            r"\bcredit risk analyst\b",
            r"\bquantitative analyst\b",
            r"\bdata surveillance analyst\b",
            r"\bfraud risk analytics\b",
        ],
    ),
    (
        "Pricing / Revenue / Finance Analytics",
        [
            r"\bpricing analyst\b",
            r"\brevenue analyst\b",
            r"\bcommercial analyst\b",
            r"\bsales analyst\b",
            r"\bfinancial (?:planning|plan).*analyst\b",
            r"\bfp(?: and |&)a analyst\b",
            r"\bfinancial analyst\b",
            r"\bfinance analyst\b",
            r"\bfinancial analysis\b.*\banalyst\b",
            r"\banalyst\b.*\bfinancial planning (?:and )?analysis\b",
            r"\bsourcing rate analyst\b",
            r"\bepm planning\b.*\banalyst\b",
            r"\bcommercial analytics\b.*\banalyst\b",
            r"\banalyst\b.*\bcommercial analytics\b",
        ],
    ),
    (
        "Strategy / Performance Analytics",
        [
            r"\bstrategy analyst\b",
            r"\bperformance analyst\b",
            r"\bdecision analyst\b",
            r"\bresearch analyst\b",
            r"\banalyst\b.*\bdata strategy\b",
        ],
    ),
]

LEADERSHIP_PATTERNS = [
    r"\b(?:data|business|advanced|risk|quantitative) analytics manager\b",
    r"\banalytics (?:manager|lead|director|head)\b",
    r"\b(?:manager|lead|director|head).*\bdata analytics\b",
    r"\breporting and analytics manager\b",
    r"\b(?:manager|lead|director|head|agm).*\bbusiness analytics\b",
    r"\bagm.*\bdata analytics\b",
    r"\bmanager\b.*\bclient analytics\b",
    r"\bclient analytics\b.*\bmanager\b",
    r"\b(?:manager|lead|director|head)\b.*\banalytics\b",
    r"\banalytics\b.*\b(?:manager|lead|director|head)\b",
]

ANALYTICAL_EVIDENCE_RULES = {
    "Query / Programming": [
        r"\bsql\b",
        r"\bpython\b",
        r"\br programming\b",
        r"\bsas\b",
        r"\bspss\b",
    ],
    "BI / Visualization": [
        r"\bpower\s*bi\b",
        r"\btableau\b",
        r"\blooker\b",
        r"\bqlik\b",
        r"\bdata visualization\b",
    ],
    "Spreadsheet Analysis": [
        r"\bexcel\b",
        r"\bvba\b",
        r"\bpivot tables?\b",
        r"\bpower query\b",
    ],
    "Data Platforms": [
        r"\bsnowflake\b",
        r"\bbigquery\b",
        r"\bredshift\b",
        r"\bdatabricks\b",
        r"\bdata warehouse\b",
        r"\bdatabase\b",
    ],
    "Analysis / Statistics": [
        r"\bdata analys(?:is|es|ing)\b",
        r"\banaly[sz](?:e|ing)\b.*\bdata(?:sets?)?\b",
        r"\bstatistical analys(?:is|es)\b",
        r"\bforecast(?:ing|s)?\b",
        r"\bregression\b",
        r"\bhypothesis test(?:ing)?\b",
        r"\ba/b test(?:ing)?\b",
    ],
    "Reporting / Metrics": [
        r"\bdashboard(?:s)?\b",
        r"\bkpi(?:s)?\b",
        r"\bperformance metrics\b",
        r"\bmanagement reporting\b",
        r"\binsights?\b",
        r"\bactionable insights?\b",
    ],
    "Data Handling": [
        r"\betl\b",
        r"\bdata (?:cleaning|validation|modelling|modeling)\b",
        r"\bdata quality\b",
        r"\bdata governance\b",
        r"\bquerying\b",
    ],
}


def analytical_evidence(value: Any) -> tuple[int, str, bool, bool]:
    text = normalized_text(value)
    matched = [
        category
        for category, patterns in ANALYTICAL_EVIDENCE_RULES.items()
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns)
    ]
    technical = any(
        category in matched
        for category in {"Query / Programming", "BI / Visualization", "Data Platforms"}
    )
    analytical_duty = any(
        category in matched
        for category in {
            "Analysis / Statistics",
            "Reporting / Metrics",
            "Data Handling",
        }
    )
    return len(matched), " | ".join(matched), technical, analytical_duty


def match_role_rule(text: str, rules: list[tuple[str, list[str]]]) -> str | None:
    for family, patterns in rules:
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            return family
    return None


def classify_role_scope(title: Any, description: Any) -> dict[str, Any]:
    title_text = normalized_text(title)
    combined_text = f"{title_text} {normalized_text(description)}"
    score, evidence, technical, analytical_duty = analytical_evidence(combined_text)

    if any(
        re.search(pattern, title_text, flags=re.I)
        for pattern in BI_HYBRID_ROLE_PATTERNS
    ):
        included = score >= 2 and analytical_duty
        return {
            "role_in_scope": included,
            "role_family": "BI / Reporting Analyst" if included else None,
            "role_rule": (
                "BI analyst / developer hybrid" if included else "BI hybrid title"
            ),
            "role_evidence_score": score,
            "role_evidence": evidence,
            "role_exclusion_reason": (
                None if included else "Insufficient analytical evidence"
            ),
        }

    for reason, patterns in TITLE_EXCLUSION_RULES:
        if any(re.search(pattern, title_text, flags=re.I) for pattern in patterns):
            return {
                "role_in_scope": False,
                "role_family": None,
                "role_rule": "Title exclusion",
                "role_evidence_score": score,
                "role_evidence": evidence,
                "role_exclusion_reason": reason,
            }

    core_family = match_role_rule(title_text, CORE_ROLE_RULES)
    if core_family:
        return {
            "role_in_scope": True,
            "role_family": core_family,
            "role_rule": "Core title",
            "role_evidence_score": score,
            "role_evidence": evidence,
            "role_exclusion_reason": None,
        }

    adjacent_family = match_role_rule(title_text, ADJACENT_ROLE_RULES)
    if adjacent_family:
        included = score >= 2 and analytical_duty
        return {
            "role_in_scope": included,
            "role_family": adjacent_family if included else None,
            "role_rule": (
                "Adjacent title with analytical evidence"
                if included
                else "Adjacent title"
            ),
            "role_evidence_score": score,
            "role_evidence": evidence,
            "role_exclusion_reason": (
                None if included else "Insufficient analytical evidence"
            ),
        }

    if any(
        re.search(pattern, title_text, flags=re.I) for pattern in LEADERSHIP_PATTERNS
    ):
        included = score >= 2 and analytical_duty
        return {
            "role_in_scope": included,
            "role_family": "Analytics Leadership" if included else None,
            "role_rule": "Analytics leadership title",
            "role_evidence_score": score,
            "role_evidence": evidence,
            "role_exclusion_reason": (
                None if included else "Insufficient analytical evidence"
            ),
        }

    generic_analyst = bool(re.search(r"\banalyst\b", title_text, flags=re.I))
    if generic_analyst:
        included = score >= 3 and technical and analytical_duty
        return {
            "role_in_scope": included,
            "role_family": "General Analytics Analyst" if included else None,
            "role_rule": (
                "Generic title with strong evidence"
                if included
                else "Generic analyst title"
            ),
            "role_evidence_score": score,
            "role_evidence": evidence,
            "role_exclusion_reason": (
                None if included else "Insufficient analytical evidence"
            ),
        }

    return {
        "role_in_scope": False,
        "role_family": None,
        "role_rule": "Outside title scope",
        "role_evidence_score": score,
        "role_evidence": evidence,
        "role_exclusion_reason": "Title is outside the analyst and analytics scope",
    }


def classify_seniority(title: Any, source_value: Any = None) -> str:
    text = normalized_text(title)
    rules = [
        ("Director / Head", r"\b(?:director|head of|vice president|vp)\b"),
        ("Manager", r"\bmanager\b"),
        ("Lead / Principal", r"\b(?:lead|principal|staff)\b"),
        ("Senior", r"\b(?:senior|sr\.?|specialist)\b"),
        ("Junior", r"\b(?:junior|jr\.?|entry[- ]level|graduate)\b"),
        ("Intern", r"\b(?:intern|internship|trainee)\b"),
    ]
    for label, pattern in rules:
        if re.search(pattern, text, flags=re.I):
            return label

    source = normalized_text(source_value)
    source_map = {
        "intern": "Intern",
        "junior": "Junior",
        "middle": "Mid",
        "senior": "Senior",
        "lead": "Lead / Principal",
        "staff": "Lead / Principal",
        "principal": "Lead / Principal",
        "c level": "Director / Head",
    }
    return source_map.get(source, "Not Specified")


def normalize_city(location: Any) -> str:
    """Normalize a true city without converting a state or missing label into one.

    Prefer the first comma-delimited locality. Global substring matching could
    previously turn 'Noida, Delhi' into Delhi or 'Mumbai, Navi Mumbai' into
    Navi Mumbai. A frozen snapshot is corrected by a *targeted* pass below.
    """
    text = normalized_text(location)
    if not text:
        return "Unknown"
    if re.search(r"\b(?:remote|work from home|wfh|work remotely)\b", text, flags=re.I):
        return "Remote - India"

    first_piece = re.split(r"[,;|/]", clean_text(location), maxsplit=1)[0].strip()
    head = normalized_text(first_piece)
    if head in {"na", "n a", "n/a", "nan", "unknown", "none", "not specified", "null"}:
        return "Unknown"
    if head in STATE_ONLY_LOCATIONS or head == "india":
        return "City Not Specified"
    if head in CITY_ALIASES:
        return CITY_ALIASES[head]
    if text in STATE_ONLY_LOCATIONS:
        return "City Not Specified"

    # Recognize an alias in an otherwise descriptive location only if there
    # isn't a clearly supplied first city to protect.
    for alias, canonical in sorted(CITY_ALIASES.items(), key=lambda pair: -len(pair[0])):
        if re.search(rf"\b{re.escape(alias)}\b", head, flags=re.I):
            return canonical
    return first_piece if first_piece else "Unknown"


def normalize_state(city: str, location: Any) -> str:
    if city in STATE_BY_CITY:
        return STATE_BY_CITY[city]

    if city == "City Not Specified":
        first = normalized_text(re.split(r"[,;|/]", clean_text(location), maxsplit=1)[0])
        known_states = {
            "maharashtra": "Maharashtra", "karnataka": "Karnataka",
            "telangana": "Telangana", "gujarat": "Gujarat",
            "haryana": "Haryana", "uttar pradesh": "Uttar Pradesh",
            "andhra pradesh": "Andhra Pradesh", "tamil nadu": "Tamil Nadu",
            "west bengal": "West Bengal", "madhya pradesh": "Madhya Pradesh",
            "rajasthan": "Rajasthan", "kerala": "Kerala",
            "punjab": "Punjab", "odisha": "Odisha",
        }
        return known_states.get(first, "India")

    text = normalized_text(location)

    state_tokens = {
        "karnataka": "Karnataka",
        "telangana": "Telangana",
        "maharashtra": "Maharashtra",
        "tamil nadu": "Tamil Nadu",
        "haryana": "Haryana",
        "uttar pradesh": "Uttar Pradesh",
        "west bengal": "West Bengal",
        "gujarat": "Gujarat",
        "kerala": "Kerala",
        "rajasthan": "Rajasthan",
        "madhya pradesh": "Madhya Pradesh",
        "odisha": "Odisha",
        "andhra pradesh": "Andhra Pradesh",
        "punjab": "Punjab",
        "delhi": "Delhi",
    }

    for token, canonical in state_tokens.items():
        if token in text:
            return canonical

    if city == "Remote - India":
        return "Remote - India"

    return "Unknown"


def is_explicit_foreign_location(value: Any) -> bool:
    """Identify explicit foreign locations that source metadata mislabeled as India."""
    text = normalized_text(value)
    return bool(
        re.search(
            r"\b(?:indianapolis|usa|united states|u s|united kingdom|canada|australia|singapore|philippines)\b",
            text,
            flags=re.I,
        )
    )


def classify_work_mode(title: Any, description: Any, location: Any) -> str:
    text = " ".join(
        [
            normalized_text(title),
            normalized_text(description),
            normalized_text(location),
        ]
    )

    if re.search(r"\bhybrid\b", text, flags=re.I):
        return "Hybrid"

    if re.search(r"\b(remote|work from home|wfh|work remotely)\b", text, flags=re.I):
        return "Remote"

    if re.search(r"\b(on[- ]?site|onsite|in[- ]office|in office)\b", text, flags=re.I):
        return "On-site"

    return "Not Specified"


def extract_experience(
    title: Any, description: Any
) -> tuple[float | None, float | None]:
    text = " ".join([clean_text(title), clean_text(description)])

    values: list[tuple[float, float]] = []

    for pattern in EXPERIENCE_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()

            try:
                low = float(groups[0])

                if len(groups) > 1 and groups[1] is not None:
                    high = float(groups[1])
                else:
                    high = low

                if 0 <= low <= 30 and 0 <= high <= 30 and high >= low:
                    values.append((low, high))
            except Exception:
                continue

    if not values:
        return None, None

    values.sort(key=lambda item: (item[0], item[1]))

    return values[0]


def experience_band(minimum: float | None) -> str:
    if minimum is None or pd.isna(minimum):
        return "Not Specified"

    value = float(minimum)

    bands = [
        (0, 1, "0–1"),
        (1, 2, "1–2"),
        (2, 3, "2–3"),
        (3, 4, "3–4"),
        (4, 5, "4–5"),
        (5, 6, "5–6"),
        (6, 7, "6–7"),
        (7, 8, "7–8"),
        (8, 9, "8–9"),
        (9, 10, "9–10"),
        (10, 15, "10–15"),
    ]

    for low, high, label in bands:
        if low <= value < high:
            return label

    return "15+"


def normalize_source_salary(
    salary_min: Any, salary_max: Any, currency: Any, period: Any, predicted: Any
) -> tuple[Any, Any, Any, bool, str]:
    minimum = pd.to_numeric(pd.Series([salary_min]), errors="coerce").iloc[0]
    maximum = pd.to_numeric(pd.Series([salary_max]), errors="coerce").iloc[0]

    if pd.isna(minimum) and pd.isna(maximum):
        return pd.NA, pd.NA, pd.NA, False, "Not disclosed"
    if pd.isna(minimum) or pd.isna(maximum):
        return pd.NA, pd.NA, pd.NA, False, "Incomplete salary range"
    if minimum <= 0 or maximum <= 0 or maximum < minimum:
        return pd.NA, pd.NA, pd.NA, False, "Invalid salary range"
    if boolean_value(predicted):
        return pd.NA, pd.NA, pd.NA, False, "Source-predicted salary"

    currency_code = clean_text(currency).upper()
    if currency_code not in {"INR", "₹", "RS", "RS."}:
        return pd.NA, pd.NA, pd.NA, False, "Unsupported or missing currency"

    period_text = normalized_text(period).replace("per ", "")
    multipliers = {"year": 1, "annual": 1, "annum": 1, "month": 12, "monthly": 12}
    multiplier = multipliers.get(period_text)
    if multiplier is None:
        return pd.NA, pd.NA, pd.NA, False, "Unsupported or missing salary period"

    annual_min = float(minimum) * multiplier
    annual_max = float(maximum) * multiplier
    midpoint = (annual_min + annual_max) / 2
    if midpoint < 100_000 or midpoint > 25_000_000:
        return pd.NA, pd.NA, pd.NA, False, "Outside plausible annual INR range"

    status = "Annual INR" if multiplier == 1 else "Annualized from monthly INR"
    return annual_min, annual_max, midpoint, True, status


def posting_age_band(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unknown"
    days = int(value)
    if days <= 7:
        return "0–7 days"
    if days <= 30:
        return "8–30 days"
    if days <= 60:
        return "31–60 days"
    if days <= 90:
        return "61–90 days"
    return "90+ days"


def normalized_signature_text(value: Any) -> str:
    text = normalized_text(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def descriptions_match(left: Any, right: Any) -> tuple[bool, float]:
    left_text = normalized_signature_text(left)
    right_text = normalized_signature_text(right)
    if not left_text or not right_text:
        return False, 0.0

    shorter, longer = sorted([left_text, right_text], key=len)
    if len(shorter) >= 120 and shorter in longer:
        return True, 1.0

    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_text[:2000], right_text[:2000]).ratio()
    score = max(jaccard, sequence)
    return score >= 0.72, score


def deduplicate_cross_source(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = df.copy()
    created_date = working["created_at"].dt.strftime("%Y-%m-%d")
    canonical_location = working.get("city", working["location_name"]).where(
        ~working.get("city", working["location_name"]).isin(
            ["Unknown", "City Not Specified"]
        ),
        working["location_name"],
    )
    working["dedupe_signature"] = (
        working["title"].map(normalized_signature_text)
        + "|"
        + working["company_name"].map(normalized_signature_text)
        + "|"
        + canonical_location.map(normalized_signature_text)
    )
    working["duplicate_group_id"] = working["dedupe_signature"].map(
        lambda value: hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    )
    working["description_priority"] = working["description_type"].eq("full").astype(int)

    removed_indices: set[int] = set()
    audit_rows: list[dict[str, Any]] = []
    candidate_groups = working.groupby("dedupe_signature", sort=False)
    for _, group in candidate_groups:
        if len(group) < 2:
            continue

        ordered = group.sort_values(
            ["description_priority", "collected_at", "job_id"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        kept_indices: list[int] = []
        for index, row in ordered.iterrows():
            duplicate_of: int | None = None
            similarity = 0.0
            for kept_index in kept_indices:
                kept = working.loc[kept_index]
                same_source = kept["api_source"] == row["api_source"]
                row_date_observed = bool(row.get("is_posting_date_observed", True))
                kept_date_observed = bool(kept.get("is_posting_date_observed", True))
                if same_source:
                    # Strict within-source rule to avoid merging two real vacancies
                    # that happen to have the same employer and job title.
                    if not (row_date_observed and kept_date_observed):
                        continue
                    if row["created_at"].date() != kept["created_at"].date():
                        continue
                    row_source_id = clean_text(row.get("source_job_id", ""))
                    kept_source_id = clean_text(kept.get("source_job_id", ""))
                    same_id = bool(
                        row_source_id
                        and kept_source_id
                        and row_source_id == kept_source_id
                    )
                    exact_description = (
                        normalized_signature_text(row["description"])
                        == normalized_signature_text(kept["description"])
                        and len(normalized_signature_text(row["description"])) >= 120
                    )
                    if not (same_id or exact_description):
                        continue
                elif row_date_observed and kept_date_observed:
                    date_gap = abs((row["created_at"] - kept["created_at"]).days)
                    if date_gap > 3:
                        continue
                matched, score = descriptions_match(
                    row["description"], kept["description"]
                )
                if same_source and same_id:
                    matched, score = True, 1.0
                if matched:
                    duplicate_of = kept_index
                    similarity = score
                    break

            if duplicate_of is None:
                kept_indices.append(index)
                continue

            removed_indices.add(index)
            kept = working.loc[duplicate_of]
            audit_rows.append(
                {
                    "duplicate_group_id": row["duplicate_group_id"],
                    "removed_job_id": row["job_id"],
                    "retained_job_id": kept["job_id"],
                    "removed_source": row["api_source"],
                    "retained_source": kept["api_source"],
                    "title": row["title"],
                    "company_name": row["company_name"],
                    "location_name": row["location_name"],
                    "posted_date": created_date.loc[index],
                    "description_similarity": round(similarity, 4),
                }
            )

    kept = working.drop(index=list(removed_indices)).drop(
        columns="description_priority"
    )
    audit = pd.DataFrame(
        audit_rows,
        columns=[
            "duplicate_group_id",
            "removed_job_id",
            "retained_job_id",
            "removed_source",
            "retained_source",
            "title",
            "company_name",
            "location_name",
            "posted_date",
            "description_similarity",
        ],
    )
    return kept, audit


def extract_skills(title: Any, description: Any) -> list[str]:
    text = " ".join([normalized_text(title), normalized_text(description)])

    skills = []

    for skill, patterns in SKILL_RULES.items():
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            skills.append(skill)

    return sorted(set(skills))


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if not RAW_FILE.exists():
        raise FileNotFoundError(f"Raw collection file not found: {RAW_FILE}")

    df = pd.read_csv(RAW_FILE, low_memory=False)
    raw_rows = len(df)
    required_columns = {
        "job_id",
        "api_source",
        "source",
        "title",
        "company_name",
        "location_name",
        "country_validation",
        "description",
        "description_type",
        "created",
        "collected_at_utc",
        "redirect_url",
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise RuntimeError(
            "Raw collection is missing required columns: " + ", ".join(missing_columns)
        )
    if df["job_id"].isna().any() or df["job_id"].astype("string").duplicated().any():
        raise RuntimeError("Raw job IDs must be present and unique.")
    if df.duplicated().any():
        raise RuntimeError("Completely duplicated raw rows are present.")

    df["created_at"] = pd.to_datetime(df["created"], errors="coerce", utc=True)
    df["collected_at"] = pd.to_datetime(
        df["collected_at_utc"], errors="coerce", utc=True
    )
    default_date_basis = df["api_source"].map(
        {
            "Adzuna": "source_created_at",
            "Freehire": "source_posted_at",
            "Jooble": "source_updated_at_proxy",
            "JSearch": "source_posted_at",
        }
    )
    supplied_date_basis = df.get(
        "posting_date_basis", pd.Series(index=df.index, dtype="object")
    ).replace("", pd.NA)
    df["posting_date_basis"] = supplied_date_basis.fillna(default_date_basis)
    df["is_posting_date_observed"] = df["posting_date_basis"].isin(
        ["source_created_at", "source_posted_at"]
    )
    invalid_dates = (
        df["created_at"].isna()
        | df["collected_at"].isna()
        | ~df["created_at"].between(WINDOW_START, WINDOW_END, inclusive="both")
    )
    if invalid_dates.any():
        raise RuntimeError(
            f"Raw date validation failed for {int(invalid_dates.sum()):,} rows."
        )
    raw_posting_age_hours = (
        (df["collected_at"] - df["created_at"]).dt.total_seconds() / 3_600
    ).where(df["is_posting_date_observed"])
    raw_timestamp_inconsistency_count = int(raw_posting_age_hours.lt(0).sum())
    severe_timestamp_inconsistencies = raw_posting_age_hours.lt(-24)
    if severe_timestamp_inconsistencies.any():
        raise RuntimeError(
            "Creation time exceeds collection time by more than 24 hours for "
            f"{int(severe_timestamp_inconsistencies.sum()):,} rows."
        )

    excluded_frames: list[pd.DataFrame] = []
    audit_columns = [
        "job_id",
        "api_source",
        "source",
        "title",
        "company_name",
        "location_name",
        "created",
        "redirect_url",
    ]

    def exclude(mask: pd.Series, stage: str, reason: Any) -> None:
        nonlocal df
        mask = mask.fillna(False).astype(bool)
        if not mask.any():
            return
        removed = df.loc[mask, audit_columns].copy()
        removed["exclusion_stage"] = stage
        if isinstance(reason, pd.Series):
            removed["exclusion_reason"] = reason.loc[mask].fillna("Unspecified")
        else:
            removed["exclusion_reason"] = str(reason)
        excluded_frames.append(removed)
        df = df.loc[~mask].copy()

    missing_required = pd.Series(False, index=df.index)
    for column in ["title", "company_name", "description", "redirect_url"]:
        missing_required |= df[column].isna() | df[column].astype(str).str.strip().eq(
            ""
        )
    exclude(missing_required, "Required fields", "Missing required analytical field")

    exclude(
        ~df["country_validation"].eq("confirmed"),
        "Geography",
        "India location was not confirmed",
    )

    exclude(
        df["location_name"].map(is_explicit_foreign_location),
        "Geography",
        "Explicit non-India location",
    )

    company_normalized = df["company_name"].map(normalized_text)
    exclude(
        company_normalized.isin(NON_PRODUCTION_COMPANY_NAMES),
        "Data quality",
        "Placeholder or test company",
    )

    role_scope = pd.DataFrame(
        [
            classify_role_scope(title, description)
            for title, description in zip(df["title"], df["description"])
        ],
        index=df.index,
    )
    df = pd.concat([df, role_scope], axis=1)
    exclude(~df["role_in_scope"], "Role scope", df["role_exclusion_reason"])

    df["company_name"] = canonicalize_company_names(df["company_name"])
    df["source_family"] = df["api_source"].fillna(df["source"].map(source_family))
    df["source_provider"] = (
        df.get("source_provider", pd.Series(index=df.index, dtype="object"))
        .fillna(df["source"].map(source_provider))
        .map(clean_text)
        .replace("", "Unknown")
    )

    df["city"] = df["location_name"].map(normalize_city)
    df["state"] = [
        normalize_state(city, location)
        for city, location in zip(df["city"], df["location_name"])
    ]
    df["location_scope"] = np.where(
        df["city"].eq("Remote - India"),
        "Remote India",
        np.where(
            df["city"].eq("City Not Specified"),
            "India - City Not Specified",
            np.where(df["city"].eq("Unknown"), "Unknown", "Specific City"),
        ),
    )

    before_deduplication = len(df)
    df, dedupe_audit = deduplicate_cross_source(df)
    duplicates_removed = before_deduplication - len(df)

    explicit_workplace = (
        df.get("workplace_type", pd.Series(index=df.index, dtype="object"))
        .map(normalized_text)
        .map(
            {
                "remote": "Remote",
                "hybrid": "Hybrid",
                "onsite": "On-site",
                "on site": "On-site",
            }
        )
    )
    inferred_workplace = pd.Series(
        [
            classify_work_mode(title, description, location)
            for title, description, location in zip(
                df["title"], df["description"], df["location_name"]
            )
        ],
        index=df.index,
    )
    df["work_mode"] = explicit_workplace.fillna(inferred_workplace)

    extracted_experience = [
        extract_experience(title, description)
        for title, description in zip(df["title"], df["description"])
    ]
    source_min = pd.to_numeric(
        df.get("experience_min_years", pd.Series(index=df.index, dtype="float")),
        errors="coerce",
    )
    source_max = pd.to_numeric(
        df.get("experience_max_years", pd.Series(index=df.index, dtype="float")),
        errors="coerce",
    )
    extracted_min = pd.Series(
        [pair[0] for pair in extracted_experience],
        index=df.index,
        dtype="float64",
    )
    extracted_max = pd.Series(
        [pair[1] for pair in extracted_experience],
        index=df.index,
        dtype="float64",
    )
    source_min = source_min.where(source_min.between(0, 30))
    source_max = source_max.where(source_max.between(0, 30))
    df["experience_min_years"] = source_min.where(source_min.notna(), extracted_min)
    df["experience_max_years"] = source_max.where(source_max.notna(), extracted_max)
    df["experience_max_years"] = df["experience_max_years"].fillna(
        df["experience_min_years"]
    )
    invalid_experience_order = df["experience_min_years"].notna() & (
        df["experience_max_years"] < df["experience_min_years"]
    )
    df.loc[invalid_experience_order, "experience_max_years"] = df.loc[
        invalid_experience_order, "experience_min_years"
    ]
    df["experience_band"] = df["experience_min_years"].map(experience_band)
    df["experience_explicit_flag"] = df["experience_min_years"].notna()
    df["seniority_level"] = [
        classify_seniority(title, raw)
        for title, raw in zip(
            df["title"],
            df.get("seniority_raw", pd.Series(index=df.index, dtype="object")),
        )
    ]
    df["entry_level_flag"] = df["seniority_level"].isin(["Intern", "Junior"]) | (
        df["experience_min_years"].notna()
        & df["experience_min_years"].le(2)
        & ~df["seniority_level"].isin(
            ["Senior", "Lead / Principal", "Manager", "Director / Head"]
        )
    )

    df["posted_date"] = df["created_at"].dt.date
    df["posted_month"] = (
        df["created_at"].dt.tz_convert(None).dt.to_period("M").astype(str)
    )
    df["posted_quarter"] = (
        df["created_at"].dt.tz_convert(None).dt.to_period("Q").astype(str)
    )
    df["week_start"] = (
        df["created_at"] - pd.to_timedelta(df["created_at"].dt.day_of_week, unit="D")
    ).dt.date
    posting_age_hours = (
        (df["collected_at"] - df["created_at"]).dt.total_seconds() / 3_600
    ).where(df["is_posting_date_observed"])
    # Adzuna occasionally reports a same-day creation time a few hours after the
    # API response was collected. Preserve both source timestamps, flag the
    # inconsistency, and use zero only for the derived age measure.
    df["posting_timestamp_inconsistency_flag"] = posting_age_hours.lt(0)
    df["posting_age_at_snapshot_days"] = np.floor(
        posting_age_hours.clip(lower=0) / 24
    ).astype("Int64")
    df["posting_age_band"] = df["posting_age_at_snapshot_days"].map(posting_age_band)

    # A reporting week runs from Monday through Sunday. Using calendar dates
    # here also avoids mixing NumPy time units with Python dates.
    recent_start_date = WINDOW_END.date() - timedelta(days=89)
    df["is_recent_90d"] = (
        df["is_posting_date_observed"]
        & df["posted_date"].ge(recent_start_date)
    )

    first_posted_date = df["posted_date"].min()
    last_posted_date = df["posted_date"].max()
    first_complete_week = first_posted_date + timedelta(
        days=(7 - first_posted_date.weekday()) % 7
    )
    last_complete_week = last_posted_date - timedelta(days=6)
    df["is_complete_week"] = (
        df["is_posting_date_observed"]
        & df["week_start"].ge(first_complete_week)
        & df["week_start"].le(last_complete_week)
    )

    df["salary_min_source"] = pd.to_numeric(df.get("salary_min"), errors="coerce")
    df["salary_max_source"] = pd.to_numeric(df.get("salary_max"), errors="coerce")
    salary_results = [
        normalize_source_salary(minimum, maximum, currency, period, predicted)
        for minimum, maximum, currency, period, predicted in zip(
            df["salary_min_source"],
            df["salary_max_source"],
            df.get("salary_currency", pd.Series(index=df.index, dtype="object")),
            df.get("salary_period", pd.Series(index=df.index, dtype="object")),
            df.get("salary_is_predicted", pd.Series(index=df.index, dtype="object")),
        )
    ]
    df["salary_min"] = [item[0] for item in salary_results]
    df["salary_max"] = [item[1] for item in salary_results]
    df["salary_midpoint"] = [item[2] for item in salary_results]
    df["salary_analysis_eligible"] = [item[3] for item in salary_results]
    df["salary_normalization_status"] = [item[4] for item in salary_results]
    df["has_salary_source"] = (
        df["salary_min_source"].notna() | df["salary_max_source"].notna()
    )
    df["salary_text_evidence"] = (
        df.get("salary_currency", pd.Series(index=df.index, dtype="object"))
        .astype("string")
        .fillna("Unknown currency")
        + " / "
        + df.get("salary_period", pd.Series(index=df.index, dtype="object"))
        .astype("string")
        .fillna("Unknown period")
    )

    skills_per_job = [
        extract_skills(title, description)
        for title, description in zip(df["title"], df["description"])
    ]
    df["skill_count"] = [len(skills) for skills in skills_per_job]
    df["has_extracted_skill"] = df["skill_count"].gt(0)
    bridge = pd.DataFrame(
        [
            {
                "job_id": job_id,
                "skill": skill,
                "skill_category": SKILL_CATEGORIES.get(skill, "Other"),
            }
            for job_id, skills in zip(df["job_id"], skills_per_job)
            for skill in skills
        ],
        columns=["job_id", "skill", "skill_category"],
    ).drop_duplicates(["job_id", "skill"])

    clean_columns = [
        "job_id",
        "source_job_id",
        "api_source",
        "source",
        "source_family",
        "source_provider",
        "snapshot_id",
        "collected_at_utc",
        "title",
        "company_name",
        "location_name",
        "country_validation",
        "city",
        "state",
        "location_scope",
        "role_family",
        "role_rule",
        "role_evidence_score",
        "role_evidence",
        "seniority_level",
        "entry_level_flag",
        "work_mode",
        "description",
        "description_type",
        "posting_date_basis",
        "is_posting_date_observed",
        "created_at",
        "posted_date",
        "posted_month",
        "posted_quarter",
        "week_start",
        "posting_timestamp_inconsistency_flag",
        "posting_age_at_snapshot_days",
        "posting_age_band",
        "is_recent_90d",
        "is_complete_week",
        "experience_min_years",
        "experience_max_years",
        "experience_band",
        "experience_explicit_flag",
        "salary_min_source",
        "salary_max_source",
        "salary_currency",
        "salary_period",
        "salary_min",
        "salary_max",
        "salary_is_predicted",
        "has_salary_source",
        "salary_analysis_eligible",
        "salary_midpoint",
        "salary_normalization_status",
        "salary_text_evidence",
        "skill_count",
        "has_extracted_skill",
        "contract_type",
        "contract_time",
        "redirect_url",
        "duplicate_group_id",
    ]
    for column in clean_columns:
        if column not in df.columns:
            df[column] = pd.NA
    clean = df[clean_columns].copy().reset_index(drop=True)

    if clean["job_id"].duplicated().any() or clean.duplicated().any():
        raise RuntimeError("Final analytical dataset contains duplicates.")
    if clean["role_family"].isna().any():
        raise RuntimeError("Final analytical dataset contains an unclassified role.")
    if (
        not pd.to_datetime(clean["created_at"], utc=True)
        .between(WINDOW_START, WINDOW_END, inclusive="both")
        .all()
    ):
        raise RuntimeError("Final analytical dataset contains an out-of-window date.")

    clean.to_csv(CLEAN_FILE, index=False, encoding="utf-8")
    bridge.to_csv(SKILLS_FILE, index=False, encoding="utf-8")
    dedupe_audit.to_csv(DEDUPE_AUDIT_FILE, index=False, encoding="utf-8")
    exclusions = (
        pd.concat(excluded_frames, ignore_index=True)
        if excluded_frames
        else pd.DataFrame(
            columns=audit_columns + ["exclusion_stage", "exclusion_reason"]
        )
    )
    exclusions.to_csv(EXCLUDED_FILE, index=False, encoding="utf-8")

    exclusion_summary = (
        exclusions["exclusion_reason"]
        .value_counts()
        .rename_axis("exclusion_reason")
        .reset_index(name="row_count")
    )
    exclusion_summary.to_csv(EXCLUSION_SUMMARY_FILE, index=False, encoding="utf-8")

    included_sample = clean.sample(n=min(50, len(clean)), random_state=42).copy()
    included_sample = included_sample[
        ["job_id", "title", "company_name", "source", "redirect_url"]
    ]
    included_sample["model_in_scope"] = True
    included_sample["model_role_family"] = clean.loc[
        included_sample.index, "role_family"
    ].values
    included_sample["model_reason"] = "Retained by role taxonomy"

    role_exclusions = exclusions.loc[
        exclusions["exclusion_stage"].eq("Role scope")
    ].copy()
    excluded_sample = role_exclusions.sample(
        n=min(50, len(role_exclusions)), random_state=42
    )
    excluded_sample = excluded_sample[
        ["job_id", "title", "company_name", "source", "redirect_url"]
    ]
    excluded_sample["model_in_scope"] = False
    excluded_sample["model_role_family"] = pd.NA
    excluded_sample["model_reason"] = role_exclusions.loc[
        excluded_sample.index, "exclusion_reason"
    ].values

    taxonomy_sample = pd.concat(
        [included_sample, excluded_sample], ignore_index=True
    ).sample(frac=1, random_state=42)
    taxonomy_sample.insert(
        0,
        "sample_id",
        [f"TAX-{number:03d}" for number in range(1, len(taxonomy_sample) + 1)],
    )
    taxonomy_sample["manual_in_scope"] = ""
    taxonomy_sample["reviewer_notes"] = ""
    taxonomy_sample.to_csv(TAXONOMY_SAMPLE_FILE, index=False, encoding="utf-8")

    role_audit = (
        clean["role_family"]
        .value_counts()
        .rename_axis("role_family")
        .reset_index(name="job_count")
    )
    role_audit["share_pct"] = (role_audit["job_count"] / len(clean) * 100).round(2)
    role_audit.to_csv(ROLE_AUDIT_FILE, index=False, encoding="utf-8")

    skill_coverage = (
        bridge.groupby(["skill", "skill_category"], as_index=False)["job_id"]
        .nunique()
        .rename(columns={"job_id": "job_count"})
        if not bridge.empty
        else pd.DataFrame(columns=["skill", "skill_category", "job_count"])
    )
    skill_coverage["share_pct"] = (
        skill_coverage["job_count"] / len(clean) * 100
    ).round(2)
    skill_coverage = skill_coverage.sort_values(
        ["job_count", "skill"], ascending=[False, True]
    )
    skill_coverage.to_csv(SKILL_COVERAGE_FILE, index=False, encoding="utf-8")

    exclusion_counts = exclusions["exclusion_reason"].value_counts()
    report_lines = [
        "DATA ANALYST JOB MARKET INTELLIGENCE — ANALYTICAL DATASET REPORT",
        "=" * 76,
        f"collection_snapshot: {SNAPSHOT_ID}",
        f"posting_window: {WINDOW_START.isoformat()} to {WINDOW_END.isoformat()}",
        f"raw_candidate_rows: {raw_rows:,}",
        f"raw_posting_timestamp_inconsistencies: {raw_timestamp_inconsistency_count:,}",
        f"role_and_quality_exclusions: {len(exclusions):,}",
        f"deduplicated_postings_removed: {duplicates_removed:,}",
        f"processed_job_rows: {len(clean):,}",
        f"skill_bridge_rows: {len(bridge):,}",
        f"unique_skills: {bridge['skill'].nunique() if not bridge.empty else 0:,}",
        f"skill_coverage_pct: {clean['has_extracted_skill'].mean() * 100:.2f}",
        f"experience_coverage_pct: {clean['experience_explicit_flag'].mean() * 100:.2f}",
        f"salary_source_coverage_pct: {clean['has_salary_source'].mean() * 100:.2f}",
        f"salary_analysis_coverage_pct: {clean['salary_analysis_eligible'].mean() * 100:.2f}",
        "retained_posting_timestamp_inconsistencies: "
        f"{clean['posting_timestamp_inconsistency_flag'].sum():,}",
        f"posting_date_proxy_rows: {(~clean['is_posting_date_observed']).sum():,}",
        "median_observed_posting_age_days: "
        f"{clean.loc[clean['is_posting_date_observed'], 'posting_age_at_snapshot_days'].median():.1f}",
        "",
        "TOP EXCLUSION REASONS",
    ]
    report_lines.extend(
        f"{reason}: {count:,}" for reason, count in exclusion_counts.head(15).items()
    )
    REPORT_FILE.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("=" * 76)
    print("ANALYTICAL DATASET CREATED")
    print("=" * 76)
    print(f"Raw candidate rows:            {raw_rows:,}")
    print(f"Role/quality exclusions:       {len(exclusions):,}")
    print(f"Cross/within-source duplicates: {duplicates_removed:,}")
    print(f"Final unique jobs:             {len(clean):,}")
    print(f"Skill bridge rows:             {len(bridge):,}")
    print(
        f"Unique extracted skills:       {bridge['skill'].nunique() if not bridge.empty else 0:,}"
    )
    print(f"Clean jobs:                    {CLEAN_FILE}")
    print(f"Excluded-posting audit:        {EXCLUDED_FILE}")
    print(f"Deduplication audit:           {DEDUPE_AUDIT_FILE}")

# ---------------------------------------------------------------------------
# Frozen-snapshot repair: does NOT require a raw collection or rerun the ETL.
# This mode changes only employer names, and invalid city/scope classifications.
# A dry-run is the default. Raw-data ETL remains available via --from-raw.
# ---------------------------------------------------------------------------


def corrected_frozen_snapshot(jobs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    needed = {
        "job_id", "company_name", "location_name", "city", "state",
        "specific_city", "location_scope", "salary_analysis_eligible",
    }
    if not needed.issubset(jobs.columns):
        raise ValueError(f"Missing frozen snapshot columns: {sorted(needed - set(jobs.columns))}")
    if len(jobs) != 5460 or jobs["job_id"].duplicated().any():
        raise ValueError("Unexpected job count or duplicate job IDs; snapshot left unchanged")

    out = jobs.copy()
    out["company_name"] = canonicalize_company_names(jobs["company_name"])

    bad_cities = {value.casefold() for value in STATE_ONLY_LOCATIONS}
    missing_cities = {"unknown", "city not specified", "na", "n/a", "nan", ""}
    city_value = out["specific_city"].str.strip().str.casefold()
    bad = out["location_scope"].eq("Specific City") & city_value.isin(bad_cities | missing_cities)
    missing = bad & city_value.isin(missing_cities)
    state_only = bad & ~missing

    # Do not infer Hyderabad from Telangana or Bengaluru from Karnataka.
    # Preserve an explicit state if available; change the city-grain fields only.
    out.loc[state_only, "city"] = "City Not Specified"
    out.loc[state_only, "location_scope"] = "India - City Not Specified"
    out.loc[missing, "city"] = "Unknown"
    out.loc[missing, "state"] = "Unknown"
    out.loc[missing, "location_scope"] = "Unknown"
    out.loc[bad, "specific_city"] = ""

    compared = ["company_name", "city", "state", "specific_city", "location_scope"]
    changed = jobs[compared].ne(out[compared]).any(axis=1)
    audit = out.loc[changed, ["job_id"]].copy()
    for field in compared:
        audit[f"old_{field}"] = jobs.loc[changed, field]
        audit[f"new_{field}"] = out.loc[changed, field]
    return out, audit


def audit_frozen_snapshot(*, apply: bool = False) -> None:
    # Strings preserve original IDs, numeric formatting, blanks and booleans.
    source = pd.read_csv(CLEAN_FILE, dtype=str, keep_default_na=False)
    updated, audit = corrected_frozen_snapshot(source)
    changed_company = int((source["company_name"] != updated["company_name"]).sum())
    changed_scope = int((source["location_scope"] != updated["location_scope"]).sum())
    before_companies = source["company_name"].nunique()
    after_companies = updated["company_name"].nunique()
    before_cities = source.loc[source.location_scope.eq("Specific City"), "specific_city"].nunique()
    after_cities = updated.loc[updated.location_scope.eq("Specific City"), "specific_city"].nunique()
    print("FROZEN ENTITY CLEANUP AUDIT")
    print(f"Jobs: {len(source):,} (unchanged)")
    print(f"Employer-name changes: {changed_company:,}")
    print(f"Employer groups: {before_companies:,} -> {after_companies:,}")
    print(f"Invalid city/scope corrections: {changed_scope:,}")
    print(f"Specific-city labels: {before_cities:,} -> {after_cities:,}")
    print(f"Rows with at least one correction: {len(audit):,}")
    print("Top employer aliases:")
    if changed_company:
        print(pd.DataFrame({
            "old": source.loc[source.company_name.ne(updated.company_name), "company_name"],
            "new": updated.loc[source.company_name.ne(updated.company_name), "company_name"],
        }).value_counts().head(15).to_string())
    print("Corrected invalid city/scope labels:")
    if changed_scope:
        print(source.loc[source.location_scope.ne(updated.location_scope), "specific_city"].value_counts().to_string())
    if not apply:
        print("DRY RUN ONLY: no data, database, Power BI or checksums modified.")
        return
    if audit.empty:
        print("No CSV changes needed; already normalized.")
        return

    # Preserve a recovery copy outside the repository, never inside data/processed.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(tempfile.gettempdir()) / f"job_market_clean_before_entity_fix_{stamp}.csv"
    shutil.copy2(CLEAN_FILE, backup)
    fd, temp_name = tempfile.mkstemp(prefix="jobs_normalized_", suffix=".csv", dir=CLEAN_FILE.parent)
    os.close(fd)
    tmp = Path(temp_name)
    try:
        updated.to_csv(tmp, index=False, encoding="utf-8")
        check = pd.read_csv(tmp, dtype=str, keep_default_na=False)
        if check.shape != source.shape or not check["job_id"].equals(source["job_id"]):
            raise RuntimeError("Post-write ID/count verification failed; original untouched")
        untouched = [x for x in source.columns if x not in
                     {"company_name", "city", "state", "specific_city", "location_scope"}]
        if not check[untouched].equals(source[untouched]):
            raise RuntimeError("Unexpected changes outside approved fields; original untouched")
        tmp.replace(CLEAN_FILE)
    finally:
        if tmp.exists():
            tmp.unlink()
    print(f"UPDATED: {CLEAN_FILE}")
    print(f"Recovery copy (outside repo): {backup}")
    print("NEXT: sync PostgreSQL in place, refresh the existing PBIX, regenerate dependent reports, and update the manifest.")


def sync_postgres(*, confirm: bool = False) -> None:
    """Transactional key remapping; never invokes schema.sql or drops the model."""
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required for --sync-postgres") from exc

    if not os.environ.get("PGPASSWORD"):
        raise RuntimeError("PGPASSWORD is not set in this terminal; do not paste it into chat")
    jobs = pd.read_csv(CLEAN_FILE, dtype=str, keep_default_na=False)
    corrected, _ = corrected_frozen_snapshot(jobs)
    if not corrected[["company_name", "city", "state", "specific_city", "location_scope"]].equals(
        jobs[["company_name", "city", "state", "specific_city", "location_scope"]]
    ):
        raise RuntimeError("Clean the CSV with --apply-existing before synchronizing PostgreSQL")

    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "job_market"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.job_id, c.company_name, l.city, l.state,
                       l.location_name, l.location_scope
                FROM job_market.fact_jobs f
                JOIN job_market.dim_company c ON c.company_key=f.company_key
                JOIN job_market.dim_location l ON l.location_key=f.location_key
            """)
            current = {str(row[0]): row[1:] for row in cur.fetchall()}
            expected_ids = set(jobs.job_id)
            if set(current) != expected_ids or len(current) != 5460:
                raise RuntimeError("PostgreSQL job IDs do not match the frozen CSV; aborted")

            changed = []
            for row in jobs.itertuples(index=False):
                desired = (row.company_name, row.city, row.state,
                           row.location_name, row.location_scope)
                if tuple(current[row.job_id]) != desired:
                    changed.append((row.job_id, *desired))
            print(f"PostgreSQL facts requiring entity updates: {len(changed)}")
            if not confirm or not changed:
                print("DRY RUN: no database changes." if not confirm else "Already synchronized.")
                conn.rollback()
                return

            desired_companies = sorted({r[1] for r in changed})
            desired_locations = sorted({(r[2], r[3], r[4], r[5]) for r in changed})
            execute_values(cur, """
                INSERT INTO job_market.dim_company(company_name) VALUES %s
                ON CONFLICT (company_name) DO NOTHING
            """, [(name,) for name in desired_companies])
            execute_values(cur, """
                INSERT INTO job_market.dim_location(city,state,location_name,location_scope)
                VALUES %s ON CONFLICT (city,state,location_name,location_scope) DO NOTHING
            """, desired_locations)

            company_keys = {}
            cur.execute("SELECT company_name, company_key FROM job_market.dim_company")
            company_keys = dict(cur.fetchall())
            cur.execute("SELECT city,state,location_name,location_scope,location_key FROM job_market.dim_location")
            location_keys = {tuple(r[:4]): r[4] for r in cur.fetchall()}
            updates = [
                (company_keys[c], location_keys[(city, state, loc, scope)], job_id)
                for job_id, c, city, state, loc, scope in changed
            ]
            cur.executemany("""
                UPDATE job_market.fact_jobs
                SET company_key=%s, location_key=%s
                WHERE job_id=%s
            """, updates)
            # Remove dimension labels no longer used by ANY job in this model.
            # Do not drop tables/views, or regenerate fact-job keys.
            cur.execute("""
                DELETE FROM job_market.dim_company c WHERE NOT EXISTS
                (SELECT 1 FROM job_market.fact_jobs f WHERE f.company_key=c.company_key)
            """)
            cur.execute("""
                DELETE FROM job_market.dim_location l WHERE NOT EXISTS
                (SELECT 1 FROM job_market.fact_jobs f WHERE f.location_key=l.location_key)
            """)
            cur.execute("SELECT COUNT(*) FROM job_market.fact_jobs")
            if cur.fetchone()[0] != 5460:
                raise RuntimeError("Fact count changed unexpectedly; rolling back")
            cur.execute("""
                SELECT COUNT(DISTINCT c.company_name)
                FROM job_market.fact_jobs f
                JOIN job_market.dim_company c ON c.company_key=f.company_key
            """)
            print(f"PostgreSQL unique employers after fix: {cur.fetchone()[0]:,}")
            conn.commit()
            print(f"DATABASE SYNC COMPLETE: updated {len(updates)} job references; keys preserved")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build or safely repair the India analyst job-market dataset")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-raw", action="store_true", help="Full rebuild (requires missing raw collection)")
    group.add_argument("--audit-existing", action="store_true", help="Preview frozen CSV changes; read-only")
    group.add_argument("--apply-existing", action="store_true", help="Apply frozen CSV entity cleanup and backup outside repo")
    group.add_argument("--sync-postgres", action="store_true", help="Sync entity references in PostgreSQL without recreating schema")
    parser.add_argument("--confirm", action="store_true", help="Apply --sync-postgres changes; omitted = dry run")
    args = parser.parse_args()
    if args.from_raw:
        main()
    elif args.audit_existing:
        audit_frozen_snapshot(apply=False)
    elif args.apply_existing:
        audit_frozen_snapshot(apply=True)
    elif args.sync_postgres:
        sync_postgres(confirm=args.confirm)
