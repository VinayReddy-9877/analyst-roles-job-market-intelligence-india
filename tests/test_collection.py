import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import collect_jobs  # noqa: E402
from collect_jobs import (  # noqa: E402
    RAW_COLUMNS,
    Collector,
    classify_freehire_country,
    completed_request_keys,
    created_in_window,
    html_to_text,
    normalize_adzuna,
    normalize_freehire,
    normalize_jsearch,
    normalize_jooble,
)


class CollectionTests(unittest.TestCase):
    def test_request_json_forwards_source_auth_header(self):
        response = io.BytesIO(b'{"status":"OK"}')
        collector = object.__new__(Collector)
        with mock.patch(
            "collect_jobs.urllib.request.urlopen", return_value=response
        ) as mocked_open:
            payload, _ = collector._request_json(
                "https://example.com/search",
                {"query": "data analyst"},
                headers={"x-api-key": "test-key"},
            )
        request = mocked_open.call_args.args[0]
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(request.get_header("X-api-key"), "test-key")

    def test_html_description_is_converted_to_plain_text(self):
        self.assertEqual(html_to_text("<p>SQL &amp; Power BI</p>"), "SQL & Power BI")

    def test_window_includes_first_and_last_second(self):
        self.assertTrue(created_in_window("2026-01-01T00:00:00Z"))
        self.assertTrue(created_in_window("2026-08-29T23:59:59Z"))

    def test_window_rejects_outside_dates(self):
        self.assertFalse(created_in_window("2025-12-31T23:59:59Z"))
        self.assertFalse(created_in_window("2026-08-30T00:00:00Z"))
        self.assertFalse(created_in_window("not-a-date"))

    def test_known_indian_city_is_confirmed(self):
        record = {
            "location": "APAC - India - Pune",
            "cities": ["Pune"],
            "countries": ["in"],
        }
        self.assertEqual(classify_freehire_country(record), "confirmed")

    def test_indiana_false_positive_is_rejected(self):
        record = {
            "location": "Terre Haute, IN",
            "cities": ["Terre Haute"],
            "countries": ["in"],
        }
        self.assertEqual(classify_freehire_country(record), "rejected")

    def test_indianapolis_false_positive_is_rejected(self):
        record = {
            "location": "Indianapolis, IN, United States",
            "cities": ["Indianapolis"],
            "countries": ["in"],
        }
        self.assertEqual(classify_freehire_country(record), "rejected")

    def test_unknown_in_location_is_ambiguous(self):
        record = {"location": "APAC", "cities": [], "countries": ["in"]}
        self.assertEqual(classify_freehire_country(record), "ambiguous")

    def test_adzuna_mapping_preserves_core_fields(self):
        record = {
            "id": "123",
            "title": "Senior Data Analyst",
            "company": {"display_name": "Example Ltd"},
            "location": {"display_name": "Bengaluru", "area": ["India", "Karnataka"]},
            "description": "SQL and Power BI",
            "category": {"label": "IT Jobs", "tag": "it-jobs"},
            "created": "2026-08-20T10:00:00Z",
            "redirect_url": "https://example.com/job/123",
        }
        row = normalize_adzuna(record, "data analyst", 1, "2026-08-29T10:00:00Z")
        self.assertEqual(row["job_id"], "adzuna:123")
        self.assertEqual(row["description_type"], "snippet")
        self.assertEqual(row["country_validation"], "confirmed")

    def test_adzuna_mapping_records_partition_location(self):
        record = {
            "id": "456",
            "title": "Reporting Analyst",
            "company": {"display_name": "Example Ltd"},
            "location": {"display_name": "Pune", "area": ["India"]},
            "description": "Reporting and dashboards",
            "created": "2026-08-20T10:00:00Z",
            "redirect_url": "https://example.com/job/456",
        }
        row = normalize_adzuna(record, "analyst", 2, "2026-08-29T10:00:00Z", "Pune")
        self.assertEqual(row["search_location"], "Pune")

    def test_completed_log_pages_are_reused_for_incremental_collection(self):
        rows = [
            {
                "api_source": "Adzuna",
                "query_type": "search_term",
                "query_value": "data analyst",
                "search_location": "India",
                "page": 3,
                "status": "success",
            },
            {
                "api_source": "Freehire",
                "query_type": "search_term",
                "query_value": "data analyst",
                "page": 4,
                "status": "success",
            },
            {
                "api_source": "Jooble",
                "query_type": "search_term",
                "query_value": "data analyst",
                "page": 7,
                "status": "success",
            },
            {
                "api_source": "JSearch",
                "query_type": "search_term",
                "query_value": "reporting analyst",
                "search_location": "Pune",
                "page": 1,
                "status": "success",
            },
        ]
        keys = completed_request_keys(rows)
        self.assertIn("adzuna|data analyst|India|3", keys)
        self.assertIn("freehire|search_term|data analyst|300", keys)
        self.assertIn("jooble|data analyst|India|7", keys)
        self.assertIn("jsearch|reporting analyst|Pune|1", keys)

    def test_freehire_mapping_uses_posted_at_as_created(self):
        record = {
            "public_slug": "sample-job",
            "source": "greenhouse",
            "title": "Data Analyst",
            "company": "Example Ltd",
            "location": "Pune, India",
            "countries": ["in"],
            "cities": ["Pune"],
            "regions": ["apac"],
            "description": "<p>SQL reporting</p>",
            "skills": ["sql"],
            "posted_at": "2026-08-20T10:00:00Z",
            "url": "https://example.com/job",
            "enrichment": {"category": "data_analytics", "experience_years_min": 2},
        }
        row = normalize_freehire(record, "data_analytics", 1, "2026-08-29T10:00:00Z")
        self.assertEqual(row["job_id"], "freehire:sample-job")
        self.assertEqual(row["created"], record["posted_at"])
        self.assertEqual(row["experience_min_years"], 2.0)
        self.assertEqual(row["description"], "SQL reporting")

    def test_jooble_mapping_labels_updated_date_as_proxy(self):
        record = {
            "id": "987",
            "title": "Product Data Analyst",
            "company": "Example Ltd",
            "location": "Bangalore",
            "snippet": "Use SQL and Power BI for product reporting.",
            "salary": "₹800,000 - ₹1,000,000 a year",
            "source": "example.com",
            "type": "Full-time",
            "link": "https://in.jooble.org/away/987",
            "updated": "2026-07-15T00:00:00Z",
        }
        row = normalize_jooble(record, "data analyst", 1, "2026-08-30T10:00:00Z")
        self.assertEqual(row["job_id"], "jooble:987")
        self.assertEqual(row["description_type"], "snippet")
        self.assertEqual(row["posting_date_basis"], "source_updated_at_proxy")
        self.assertEqual(row["created"], record["updated"])
        self.assertEqual(row["salary_text"], record["salary"])

    def test_jooble_mapping_records_partition_location(self):
        record = {
            "id": "988",
            "title": "Data Analyst",
            "company": "Example Ltd",
            "location": "Hyderabad",
            "snippet": "SQL reporting",
            "source": "example.com",
            "link": "https://in.jooble.org/away/988",
            "updated": "2026-07-15T00:00:00Z",
        }
        row = normalize_jooble(
            record, "data analyst", 1, "2026-08-30T10:00:00Z", "Hyderabad"
        )
        self.assertEqual(row["search_location"], "Hyderabad")

    def test_jsearch_mapping_preserves_full_posting_fields(self):
        record = {
            "job_id": "abc123",
            "job_title": "Data Analyst",
            "employer_name": "Example Ltd",
            "job_publisher": "Example Careers",
            "job_description": "Use SQL and Power BI to build dashboards.",
            "job_location": "Pune, Maharashtra",
            "job_city": "Pune",
            "job_state": "Maharashtra",
            "job_country": "IN",
            "job_posted_at_datetime_utc": "2026-08-20T10:00:00Z",
            "job_apply_link": "https://example.com/jobs/abc123",
            "job_employment_type": "Full-time",
            "job_is_remote": False,
            "job_min_salary": 800000,
            "job_max_salary": 1000000,
            "job_salary_period": "YEAR",
            "required_technologies": ["SQL", "Power BI"],
        }
        row = normalize_jsearch(record, "data analyst", "Pune", "2026-08-30T10:00:00Z")
        self.assertEqual(row["job_id"], "jsearch:abc123")
        self.assertEqual(row["description_type"], "full")
        self.assertEqual(row["posting_date_basis"], "source_posted_at")
        self.assertEqual(row["country_validation"], "confirmed")
        self.assertEqual(row["search_location"], "Pune")
        self.assertEqual(row["salary_min"], 800000.0)

    def test_finalize_streams_existing_csv_and_merges_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_file = root / "raw.csv"
            checkpoint_rows = root / ".rows.jsonl"
            checkpoint_state = root / ".state.json"
            collection_log = root / "collection_log.csv"
            manifest_file = root / "manifest.json"

            existing = normalize_adzuna(
                {
                    "id": "123",
                    "title": "Data Analyst",
                    "company": {"display_name": "Example Ltd"},
                    "location": {"display_name": "Bengaluru", "area": ["India"]},
                    "description": "SQL reporting",
                    "created": "2026-08-20T10:00:00Z",
                    "redirect_url": "https://example.com/123",
                },
                "data analyst",
                1,
                "2026-08-29T10:00:00Z",
            )
            with raw_file.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
                writer.writeheader()
                writer.writerow(
                    {column: existing.get(column, "") for column in RAW_COLUMNS}
                )

            jooble_record = {
                "id": "987",
                "title": "Product Data Analyst",
                "company": "Example Ltd",
                "location": "Bangalore",
                "snippet": "SQL and Power BI",
                "source": "example.com",
                "link": "https://in.jooble.org/away/987",
                "updated": "2026-07-15T00:00:00Z",
            }
            first = normalize_jooble(
                jooble_record, "data analyst", 1, "2026-08-30T10:00:00Z"
            )
            second = normalize_jooble(
                jooble_record, "product analyst", 1, "2026-08-30T11:00:00Z"
            )
            checkpoint_rows.write_text(
                "\n".join(json.dumps(row) for row in (first, second)) + "\n",
                encoding="utf-8",
            )

            with mock.patch.multiple(
                collect_jobs,
                RAW_DIR=root,
                RAW_FILE=raw_file,
                CHECKPOINT_ROWS_FILE=checkpoint_rows,
                CHECKPOINT_STATE_FILE=checkpoint_state,
                COLLECTION_LOG_FILE=collection_log,
                COLLECTION_MANIFEST_FILE=manifest_file,
            ):
                summary = Collector().finalize()

            with raw_file.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["rows"], 2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["job_id"] for row in rows}), 2)
            jooble = next(row for row in rows if row["api_source"] == "Jooble")
            self.assertEqual(
                jooble["matched_search_terms"], "data analyst|product analyst"
            )
            self.assertFalse(checkpoint_rows.exists())
            self.assertTrue(manifest_file.exists())


if __name__ == "__main__":
    unittest.main()
