"""Shared project configuration.

Credentials are read from environment variables by the collection script and
are deliberately not stored here.
"""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

WINDOW_START = pd.Timestamp("2026-01-01T00:00:00Z")
WINDOW_END = pd.Timestamp("2026-08-29T23:59:59Z")
SNAPSHOT_ID = "2026-08-30"
POSTED_WITHIN_DAYS = (WINDOW_END.date() - WINDOW_START.date()).days + 1

RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"

RAW_FILE = RAW_DIR / "job_postings_raw_20260829.csv"
CLEAN_FILE = PROCESSED_DIR / "job_postings_clean.csv"
SKILLS_FILE = PROCESSED_DIR / "job_skills_bridge.csv"
COLLECTION_LOG_FILE = RAW_DIR / "collection_log.csv"
COLLECTION_MANIFEST_FILE = RAW_DIR / "collection_manifest.json"
EXCLUDED_FILE = INTERIM_DIR / "excluded_postings.csv"
DEDUPE_AUDIT_FILE = INTERIM_DIR / "deduplication_audit.csv"
EXCLUSION_SUMMARY_FILE = REPORT_DIR / "exclusion_reason_summary.csv"
TAXONOMY_SAMPLE_FILE = REPORT_DIR / "taxonomy_validation_sample.csv"


ADZUNA_API_ROOT = "https://api.adzuna.com/v1/api/jobs/in/search"
FREEHIRE_SEARCH_URL = "https://freehire.me/api/v1/agent/jobs/search"
JOOBLE_API_ROOT = "https://in.jooble.org/api"
JSEARCH_API_ROOT = "https://api.openwebninja.com/jsearch/search-v2"

REQUEST_TIMEOUT_SECONDS = 60
MAX_REQUEST_ATTEMPTS = 5
RETRY_BASE_SECONDS = 2

ADZUNA_RESULTS_PER_PAGE = 50
ADZUNA_MAX_PAGES_PER_QUERY = 8
FREEHIRE_RESULTS_PER_PAGE = 100
JOOBLE_RESULTS_PER_PAGE = 100
JSEARCH_NUM_PAGES = 5

# Final free-quota pass for markets not covered by the India-wide and first
# city-partitioned pulls. The six terms below had the strongest validated
# conversion in the earlier Jooble run. Sixty planned requests leave a safety
# margin against the source's 500-request lifetime allowance.
JOOBLE_SEARCH_LOCATIONS = (
    "Ahmedabad",
    "Jaipur",
    "Kochi",
    "Coimbatore",
    "Chandigarh",
    "Indore",
    "Bhubaneswar",
    "Lucknow",
    "Vadodara",
    "Surat",
)

JOOBLE_TERM_PAGE_BUDGETS = (
    ("data analyst", 1),
    ("reporting analyst", 1),
    ("BI analyst", 1),
    ("insights analyst", 1),
    ("MIS analyst", 1),
    ("analytics analyst", 1),
)

JOOBLE_QUERY_PLAN = tuple(
    (term, location, page_limit)
    for location in JOOBLE_SEARCH_LOCATIONS
    for term, page_limit in JOOBLE_TERM_PAGE_BUDGETS
)

# One request returns up to five result pages (about 50 jobs). The free JSearch
# plan allows 200 monthly requests. These 180 city/title partitions leave room
# for smoke tests, timeouts and a small operational reserve.
JSEARCH_SEARCH_LOCATIONS = (
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Mumbai",
    "Chennai",
    "Delhi",
    "Noida",
    "Gurugram",
    "Kolkata",
)

JSEARCH_SEARCH_TERMS = (
    "data analyst",
    "senior data analyst",
    "junior data analyst",
    "business analyst",
    "senior business analyst",
    "BI analyst",
    "reporting analyst",
    "MIS analyst",
    "analytics analyst",
    "insights analyst",
    "product analyst",
    "operations analyst",
    "risk analyst",
    "marketing analyst",
    "data quality analyst",
    "data governance analyst",
    "pricing analyst",
    "revenue analyst",
    "strategy analyst",
    "supply chain analyst",
)

JSEARCH_QUERY_PLAN = tuple(
    (term, location)
    for location in JSEARCH_SEARCH_LOCATIONS
    for term in JSEARCH_SEARCH_TERMS
)

ADZUNA_SEARCH_TERMS = (
    "data analyst",
    "business analyst",
    "business intelligence analyst",
    "BI analyst",
    "reporting analyst",
    "MIS analyst",
    "analytics analyst",
    "analytics associate",
    "product analyst",
    "marketing analyst",
    "customer insights analyst",
    "operations analyst",
    "risk analyst",
    "fraud analyst",
    "pricing analyst",
    "revenue analyst",
    "commercial analyst",
    "strategy analyst",
    "performance analyst",
    "data quality analyst",
    "data governance analyst",
    "financial planning analyst",
    "quantitative analyst",
    "decision analyst",
    "insights analyst",
    "data visualization analyst",
    "data reporting analyst",
    "dashboard analyst",
    "decision science analyst",
    "people analytics analyst",
    "workforce analyst",
    "HR analytics analyst",
    "sales analyst",
    "sales operations analyst",
    "supply chain analyst",
    "procurement analyst",
    "demand planning analyst",
    "inventory analyst",
    "logistics analyst",
    "FP&A analyst",
    "research analyst",
    "digital analyst",
    "web analyst",
    "CRM analyst",
    "customer analytics analyst",
    "market intelligence analyst",
    "data management analyst",
    "master data analyst",
    "data operations analyst",
    "credit risk analyst",
    "commercial insights analyst",
    "forecasting analyst",
    "Power BI analyst",
    "Tableau analyst",
    "SQL analyst",
)

# Broad terms are partitioned by location because a single India-wide result
# can hit the API paging ceiling. Source IDs are deduplicated after collection.
ADZUNA_BROAD_SEARCH_TERMS = ("analyst", "analytics")
ADZUNA_BROAD_SEARCH_LOCATIONS = (
    "Ahmedabad",
    "Jaipur",
    "Kochi",
    "Coimbatore",
    "Chandigarh",
    "Indore",
    "Bhubaneswar",
    "Lucknow",
    "Vadodara",
    "Surat",
    "Nagpur",
    "Mysuru",
)

FREEHIRE_CATEGORIES = ("data_analytics", "business_analysis")

FREEHIRE_SEARCH_TERMS = (
    "data analyst",
    "business analyst",
    "business intelligence analyst",
    "reporting analyst",
    "MIS analyst",
    "product analyst",
    "marketing analyst",
    "customer insights analyst",
    "operations analyst",
    "risk analyst",
    "fraud analyst",
    "pricing analyst",
    "revenue analyst",
    "commercial analyst",
    "data quality analyst",
    "data governance analyst",
    "financial planning analyst",
    "quantitative analyst",
    "analyst",
    "analytics",
    "insights analyst",
    "data visualization analyst",
    "data reporting analyst",
    "dashboard analyst",
    "decision science analyst",
    "people analytics analyst",
    "workforce analyst",
    "HR analytics analyst",
    "sales analyst",
    "sales operations analyst",
    "supply chain analyst",
    "procurement analyst",
    "demand planning analyst",
    "inventory analyst",
    "logistics analyst",
    "FP&A analyst",
    "research analyst",
    "digital analyst",
    "web analyst",
    "CRM analyst",
    "customer analytics analyst",
    "market intelligence analyst",
    "data management analyst",
    "master data analyst",
    "data operations analyst",
    "credit risk analyst",
    "commercial insights analyst",
    "forecasting analyst",
    "Power BI analyst",
    "Tableau analyst",
    "SQL analyst",
)
