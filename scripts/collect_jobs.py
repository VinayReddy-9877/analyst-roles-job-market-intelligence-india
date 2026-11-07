"""Collect a fresh, reproducible snapshot of analyst jobs in India.

The collector queries Adzuna, Freehire, Jooble and JSearch, standardizes their responses, and
deduplicates repeated query hits by source job identifier. It is resumable: a
completed page is written to a temporary JSONL file before the next request.
No synthetic records are created.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from config import (
    ADZUNA_API_ROOT,
    ADZUNA_BROAD_SEARCH_LOCATIONS,
    ADZUNA_BROAD_SEARCH_TERMS,
    ADZUNA_MAX_PAGES_PER_QUERY,
    ADZUNA_RESULTS_PER_PAGE,
    ADZUNA_SEARCH_TERMS,
    COLLECTION_LOG_FILE,
    COLLECTION_MANIFEST_FILE,
    FREEHIRE_CATEGORIES,
    FREEHIRE_RESULTS_PER_PAGE,
    FREEHIRE_SEARCH_TERMS,
    FREEHIRE_SEARCH_URL,
    JOOBLE_API_ROOT,
    JOOBLE_QUERY_PLAN,
    JOOBLE_RESULTS_PER_PAGE,
    JSEARCH_API_ROOT,
    JSEARCH_NUM_PAGES,
    JSEARCH_QUERY_PLAN,
    MAX_REQUEST_ATTEMPTS,
    POSTED_WITHIN_DAYS,
    RAW_DIR,
    RAW_FILE,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BASE_SECONDS,
    SNAPSHOT_ID,
    WINDOW_END,
    WINDOW_START,
)


CHECKPOINT_ROWS_FILE = RAW_DIR / ".collection_rows.jsonl"
CHECKPOINT_STATE_FILE = RAW_DIR / ".collection_state.json"

RAW_COLUMNS = [
    "job_id",
    "source_job_id",
    "source_job_key",
    "api_source",
    "source",
    "source_provider",
    "search_term",
    "matched_search_terms",
    "search_location",
    "source_page",
    "collected_at_utc",
    "snapshot_id",
    "title",
    "company_name",
    "location_name",
    "location_area",
    "country_validation",
    "latitude",
    "longitude",
    "description",
    "description_type",
    "posting_date_basis",
    "category_label",
    "category_tag",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_text",
    "salary_is_predicted",
    "contract_type",
    "contract_time",
    "workplace_type",
    "experience_min_years",
    "experience_max_years",
    "seniority_raw",
    "skills_raw",
    "created",
    "redirect_url",
    "source_updated_at",
    "source_last_seen_at",
    "source_reality",
]

INDIA_PLACE_TERMS = {
    "india",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "mumbai",
    "pune",
    "chennai",
    "delhi",
    "new delhi",
    "noida",
    "gurugram",
    "gurgaon",
    "kolkata",
    "ahmedabad",
    "kochi",
    "cochin",
    "jaipur",
    "vadodara",
    "surat",
    "indore",
    "bhopal",
    "chandigarh",
    "thiruvananthapuram",
    "trivandrum",
    "coimbatore",
    "lucknow",
    "nagpur",
    "mysuru",
    "mysore",
    "visakhapatnam",
    "vijayawada",
    "bhubaneswar",
    "karnataka",
    "telangana",
    "maharashtra",
    "tamil nadu",
    "kerala",
    "gujarat",
    "rajasthan",
    "uttar pradesh",
    "west bengal",
    "madhya pradesh",
    "odisha",
    "andhra pradesh",
    "haryana",
    "punjab",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def html_to_text(value: Any) -> str:
    if value is None:
        return ""
    raw = html.unescape(str(value))
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def json_list(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "[]"


def created_in_window(value: Any) -> bool:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return bool(pd.notna(parsed) and WINDOW_START <= parsed <= WINDOW_END)


def classify_freehire_country(record: dict[str, Any]) -> str:
    location = str(record.get("location") or "").strip().lower()
    cities = [str(item).strip().lower() for item in record.get("cities") or []]
    countries = [str(item).strip().lower() for item in record.get("countries") or []]
    searchable = " | ".join([location, *cities])

    if any(
        re.search(rf"\b{re.escape(term)}\b", searchable) for term in INDIA_PLACE_TERMS
    ):
        return "confirmed"

    if "in" not in countries:
        return "rejected"

    # Freehire occasionally interprets the US state abbreviation "IN" as
    # India. Unknown cities followed by ", IN" are therefore not accepted.
    if re.search(r",\s*in(?:\b|\s*/)", location):
        return "rejected"

    return "ambiguous"


def normalize_adzuna(
    record: dict[str, Any],
    search_term: str,
    page: int,
    collected_at: str,
    search_location: str = "India",
) -> dict[str, Any]:
    source_id = str(record.get("id") or "").strip()
    location = record.get("location") or {}
    company = record.get("company") or {}
    category = record.get("category") or {}
    salary_present = (
        record.get("salary_min") is not None or record.get("salary_max") is not None
    )

    return {
        "job_id": f"adzuna:{source_id}",
        "source_job_id": source_id,
        "source_job_key": f"adzuna:{source_id}",
        "api_source": "Adzuna",
        "source": "Adzuna API",
        "source_provider": "Adzuna",
        "search_term": search_term,
        "matched_search_terms": search_term,
        "search_location": search_location,
        "source_page": page,
        "collected_at_utc": collected_at,
        "snapshot_id": SNAPSHOT_ID,
        "title": html_to_text(record.get("title")),
        "company_name": html_to_text(company.get("display_name")),
        "location_name": html_to_text(location.get("display_name")),
        "location_area": json_list(location.get("area")),
        "country_validation": "confirmed",
        "latitude": as_number(record.get("latitude")),
        "longitude": as_number(record.get("longitude")),
        "description": html_to_text(record.get("description")),
        "description_type": "snippet",
        "posting_date_basis": "source_created_at",
        "category_label": category.get("label"),
        "category_tag": category.get("tag"),
        "salary_min": as_number(record.get("salary_min")),
        "salary_max": as_number(record.get("salary_max")),
        "salary_currency": "INR" if salary_present else None,
        "salary_period": "year" if salary_present else None,
        "salary_text": None,
        "salary_is_predicted": record.get("salary_is_predicted"),
        "contract_type": record.get("contract_type"),
        "contract_time": record.get("contract_time"),
        "workplace_type": None,
        "experience_min_years": None,
        "experience_max_years": None,
        "seniority_raw": None,
        "skills_raw": "[]",
        "created": record.get("created"),
        "redirect_url": record.get("redirect_url"),
        "source_updated_at": None,
        "source_last_seen_at": None,
        "source_reality": None,
    }


def normalize_freehire(
    record: dict[str, Any], search_term: str, page: int, collected_at: str
) -> dict[str, Any]:
    enrichment = record.get("enrichment") or {}
    reality = record.get("reality") or {}
    source_id = str(
        record.get("public_slug") or record.get("external_id") or ""
    ).strip()
    provider = str(record.get("source") or "unknown").strip().lower()

    return {
        "job_id": f"freehire:{source_id}",
        "source_job_id": source_id,
        "source_job_key": f"freehire:{source_id}",
        "api_source": "Freehire",
        "source": f"Freehire API / {provider}",
        "source_provider": provider,
        "search_term": search_term,
        "matched_search_terms": search_term,
        "search_location": "India",
        "source_page": page,
        "collected_at_utc": collected_at,
        "snapshot_id": SNAPSHOT_ID,
        "title": html_to_text(record.get("title")),
        "company_name": html_to_text(record.get("company")),
        "location_name": html_to_text(record.get("location")),
        "location_area": json.dumps(
            {
                "countries": record.get("countries") or [],
                "regions": record.get("regions") or [],
                "cities": record.get("cities") or [],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "country_validation": classify_freehire_country(record),
        "latitude": None,
        "longitude": None,
        "description": html_to_text(record.get("description")),
        "description_type": "full",
        "posting_date_basis": "source_posted_at",
        "category_label": enrichment.get("category"),
        "category_tag": enrichment.get("category"),
        "salary_min": as_number(enrichment.get("salary_min")),
        "salary_max": as_number(enrichment.get("salary_max")),
        "salary_currency": enrichment.get("salary_currency"),
        "salary_period": enrichment.get("salary_period"),
        "salary_text": None,
        "salary_is_predicted": False,
        "contract_type": enrichment.get("employment_type"),
        "contract_time": enrichment.get("employment_type"),
        "workplace_type": enrichment.get("work_mode"),
        "experience_min_years": as_number(enrichment.get("experience_years_min")),
        "experience_max_years": as_number(enrichment.get("experience_years_max")),
        "seniority_raw": enrichment.get("seniority"),
        "skills_raw": json_list(record.get("skills")),
        "created": record.get("posted_at"),
        "redirect_url": record.get("url"),
        "source_updated_at": record.get("updated_at"),
        "source_last_seen_at": record.get("last_seen_at"),
        "source_reality": reality.get("class"),
    }


def normalize_jooble(
    record: dict[str, Any],
    search_term: str,
    page: int,
    collected_at: str,
    search_location: str = "India",
) -> dict[str, Any]:
    source_id = str(record.get("id") or "").strip()
    provider = html_to_text(record.get("source")) or "Jooble"
    updated = record.get("updated")
    return {
        "job_id": f"jooble:{source_id}",
        "source_job_id": source_id,
        "source_job_key": f"jooble:{source_id}",
        "api_source": "Jooble",
        "source": f"Jooble API / {provider}",
        "source_provider": provider,
        "search_term": search_term,
        "matched_search_terms": search_term,
        "search_location": search_location,
        "source_page": page,
        "collected_at_utc": collected_at,
        "snapshot_id": SNAPSHOT_ID,
        "title": html_to_text(record.get("title")),
        "company_name": html_to_text(record.get("company")),
        "location_name": html_to_text(record.get("location")),
        "location_area": "[]",
        "country_validation": "confirmed",
        "latitude": None,
        "longitude": None,
        "description": html_to_text(record.get("snippet")),
        "description_type": "snippet",
        "posting_date_basis": "source_updated_at_proxy",
        "category_label": None,
        "category_tag": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "salary_text": html_to_text(record.get("salary")),
        "salary_is_predicted": False,
        "contract_type": record.get("type"),
        "contract_time": record.get("type"),
        "workplace_type": None,
        "experience_min_years": None,
        "experience_max_years": None,
        "seniority_raw": None,
        "skills_raw": "[]",
        # Jooble exposes an updated timestamp, not the original creation time.
        # It is retained as a window proxy and explicitly labelled above.
        "created": updated,
        "redirect_url": record.get("link"),
        "source_updated_at": updated,
        "source_last_seen_at": None,
        "source_reality": None,
    }


def normalize_jsearch(
    record: dict[str, Any], search_term: str, search_location: str, collected_at: str
) -> dict[str, Any]:
    source_id = str(record.get("job_id") or record.get("job_uid") or "").strip()
    publisher = html_to_text(record.get("job_publisher")) or "JSearch"
    posted = record.get("job_posted_at_datetime_utc")
    if not posted and record.get("job_posted_at_timestamp") is not None:
        try:
            posted = datetime.fromtimestamp(
                float(record["job_posted_at_timestamp"]), timezone.utc
            ).isoformat()
        except (TypeError, ValueError, OSError):
            posted = None

    country = html_to_text(record.get("job_country")).upper()
    if country in {"IN", "IND", "INDIA"}:
        country_validation = "confirmed"
    elif country:
        country_validation = "rejected"
    else:
        country_validation = "ambiguous"

    employment_types = record.get("job_employment_types")
    if isinstance(employment_types, list):
        employment_types = "|".join(str(value) for value in employment_types)
    remote = record.get("job_is_remote")
    workplace_type = (
        "Remote" if remote is True else ("On-site" if remote is False else None)
    )
    required_technologies = record.get("required_technologies")
    if not isinstance(required_technologies, list):
        required_technologies = []

    return {
        "job_id": f"jsearch:{source_id}",
        "source_job_id": source_id,
        "source_job_key": f"jsearch:{source_id}",
        "api_source": "JSearch",
        "source": f"JSearch API / {publisher}",
        "source_provider": publisher,
        "search_term": search_term,
        "matched_search_terms": search_term,
        "search_location": search_location,
        "source_page": 1,
        "collected_at_utc": collected_at,
        "snapshot_id": SNAPSHOT_ID,
        "title": html_to_text(record.get("job_title")),
        "company_name": html_to_text(record.get("employer_name")),
        "location_name": html_to_text(record.get("job_location")),
        "location_area": json.dumps(
            [
                value
                for value in (record.get("job_city"), record.get("job_state"), country)
                if value
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "country_validation": country_validation,
        "latitude": as_number(record.get("job_latitude")),
        "longitude": as_number(record.get("job_longitude")),
        "description": html_to_text(record.get("job_description")),
        "description_type": "full",
        "posting_date_basis": "source_posted_at",
        "category_label": None,
        "category_tag": None,
        "salary_min": as_number(record.get("job_min_salary")),
        "salary_max": as_number(record.get("job_max_salary")),
        "salary_currency": record.get("job_salary_currency"),
        "salary_period": record.get("job_salary_period"),
        "salary_text": html_to_text(
            record.get("job_salary_string") or record.get("job_salary")
        ),
        "salary_is_predicted": False,
        "contract_type": record.get("job_employment_type"),
        "contract_time": employment_types or record.get("job_employment_type"),
        "workplace_type": workplace_type,
        "experience_min_years": as_number(record.get("required_experience_years")),
        "experience_max_years": as_number(record.get("required_experience_years")),
        "seniority_raw": record.get("seniority_level"),
        "skills_raw": json_list(required_technologies),
        "created": posted,
        "redirect_url": record.get("job_apply_link") or record.get("job_google_link"),
        "source_updated_at": None,
        "source_last_seen_at": None,
        "source_reality": publisher,
    }


def completed_request_keys(log_rows: list[dict[str, Any]]) -> set[str]:
    completed: set[str] = set()
    for row in log_rows:
        if str(row.get("status", "success")).lower() != "success":
            continue
        source = str(row.get("api_source") or "")
        query_type = str(row.get("query_type") or "")
        query_value = str(row.get("query_value") or "")
        page = int(row.get("page") or 1)
        if source == "Adzuna":
            location = str(row.get("search_location") or "India")
            if location.lower() == "nan":
                location = "India"
            completed.add(f"adzuna|{query_value}|{location}|{page}")
        elif source == "Freehire":
            offset = (page - 1) * FREEHIRE_RESULTS_PER_PAGE
            completed.add(f"freehire|{query_type}|{query_value}|{offset}")
        elif source == "Jooble":
            location = str(row.get("search_location") or "India")
            if location.lower() == "nan":
                location = "India"
            completed.add(f"jooble|{query_value}|{location}|{page}")
        elif source == "JSearch":
            location = str(row.get("search_location") or "India")
            if location.lower() == "nan":
                location = "India"
            completed.add(f"jsearch|{query_value}|{location}|{page}")
    return completed


class Collector:
    def __init__(self) -> None:
        self.existing_raw_available = RAW_FILE.exists()
        self.completed_requests = self._load_state()
        if COLLECTION_LOG_FILE.exists():
            self.log_rows = pd.read_csv(COLLECTION_LOG_FILE).to_dict("records")
        else:
            self.log_rows: list[dict[str, Any]] = []
        if not self.completed_requests and self.log_rows:
            self.completed_requests = completed_request_keys(self.log_rows)

    @staticmethod
    def _load_state() -> set[str]:
        if not CHECKPOINT_STATE_FILE.exists():
            return set()
        payload = json.loads(CHECKPOINT_STATE_FILE.read_text(encoding="utf-8"))
        return set(payload.get("completed_requests", []))

    def _save_state(self) -> None:
        CHECKPOINT_STATE_FILE.write_text(
            json.dumps(
                {"completed_requests": sorted(self.completed_requests)}, indent=2
            ),
            encoding="utf-8",
        )

    def _request_json(
        self, url: str, params: dict[str, Any], headers: dict[str, str] | None = None
    ) -> tuple[dict[str, Any], float]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                request_url = f"{url}?{urllib.parse.urlencode(params)}"
                request_headers = {
                    "Accept": "application/json",
                    "User-Agent": "india-analyst-market-research/1.0",
                }
                request_headers.update(headers or {})
                request = urllib.request.Request(request_url, headers=request_headers)
                with urllib.request.urlopen(
                    request, timeout=REQUEST_TIMEOUT_SECONDS
                ) as response:
                    payload = json.load(response)
                elapsed = time.perf_counter() - started
                if isinstance(payload, dict) and payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                return payload, elapsed
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429 or exc.code >= 500:
                    retry_after = exc.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after
                        else RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    )
                    if attempt < MAX_REQUEST_ATTEMPTS:
                        time.sleep(delay + random.uniform(0, 0.5))
                        continue
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                RuntimeError,
            ) as exc:
                last_error = exc
                if attempt == MAX_REQUEST_ATTEMPTS:
                    break
                time.sleep(
                    RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                )
        raise RuntimeError(
            f"Request failed after {MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
        )

    def _request_json_post(
        self, url: str, payload_data: dict[str, Any]
    ) -> tuple[dict[str, Any], float]:
        encoded = json.dumps(payload_data).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                request = urllib.request.Request(
                    url,
                    data=encoded,
                    method="POST",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "india-analyst-market-research/1.0",
                    },
                )
                with urllib.request.urlopen(
                    request, timeout=REQUEST_TIMEOUT_SECONDS
                ) as response:
                    payload = json.load(response)
                elapsed = time.perf_counter() - started
                if isinstance(payload, dict) and payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                return payload, elapsed
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429 or exc.code >= 500:
                    retry_after = exc.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after
                        else RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    )
                    if attempt < MAX_REQUEST_ATTEMPTS:
                        time.sleep(delay + random.uniform(0, 0.5))
                        continue
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                RuntimeError,
            ) as exc:
                last_error = exc
                if attempt == MAX_REQUEST_ATTEMPTS:
                    break
                time.sleep(
                    RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                )
        raise RuntimeError(
            f"Request failed after {MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
        )

    @staticmethod
    def _append_records(records: Iterable[dict[str, Any]]) -> None:
        with CHECKPOINT_ROWS_FILE.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _record_page(
        self,
        *,
        request_key: str,
        api_source: str,
        query_type: str,
        query_value: str,
        search_location: str,
        page: int,
        reported_total: int | None,
        returned: int,
        accepted: int,
        outside_window: int,
        elapsed: float,
        ignored_params: Any = None,
    ) -> None:
        self.log_rows.append(
            {
                "api_source": api_source,
                "query_type": query_type,
                "query_value": query_value,
                "search_location": search_location,
                "page": page,
                "reported_total": reported_total,
                "returned": returned,
                "accepted_in_window": accepted,
                "outside_window": outside_window,
                "elapsed_seconds": round(elapsed, 3),
                "ignored_params": json.dumps(
                    ignored_params or [], separators=(",", ":")
                ),
                "status": "success",
                "completed_at_utc": utc_now(),
            }
        )
        pd.DataFrame(self.log_rows).to_csv(
            COLLECTION_LOG_FILE, index=False, encoding="utf-8"
        )
        self.completed_requests.add(request_key)
        self._save_state()

    def _collect_adzuna_query(
        self, app_id: str, app_key: str, term: str, location: str
    ) -> None:
        for page in range(1, ADZUNA_MAX_PAGES_PER_QUERY + 1):
            request_key = f"adzuna|{term}|{location}|{page}"
            if request_key in self.completed_requests:
                continue

            payload, elapsed = self._request_json(
                f"{ADZUNA_API_ROOT}/{page}",
                {
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": term,
                    "where": location,
                    "results_per_page": ADZUNA_RESULTS_PER_PAGE,
                    "max_days_old": POSTED_WITHIN_DAYS,
                    "sort_by": "date",
                    "content-type": "application/json",
                },
            )
            raw_rows = payload.get("results") or []
            collected_at = utc_now()
            normalized = [
                normalize_adzuna(item, term, page, collected_at, location)
                for item in raw_rows
                if str(item.get("id") or "").strip()
            ]
            accepted = [row for row in normalized if created_in_window(row["created"])]
            self._append_records(accepted)
            self._record_page(
                request_key=request_key,
                api_source="Adzuna",
                query_type="search_term",
                query_value=term,
                search_location=location,
                page=page,
                reported_total=payload.get("count"),
                returned=len(raw_rows),
                accepted=len(accepted),
                outside_window=len(normalized) - len(accepted),
                elapsed=elapsed,
            )
            print(f"  {term!r} in {location!r}: page {page}, rows {len(raw_rows)}")
            if len(raw_rows) < ADZUNA_RESULTS_PER_PAGE:
                break

    def collect_adzuna(self, app_id: str, app_key: str) -> None:
        print("\nCollecting Adzuna")
        for term in ADZUNA_SEARCH_TERMS:
            self._collect_adzuna_query(app_id, app_key, term, "India")
        for term in ADZUNA_BROAD_SEARCH_TERMS:
            for location in ADZUNA_BROAD_SEARCH_LOCATIONS:
                self._collect_adzuna_query(app_id, app_key, term, location)

    def _collect_freehire_query(self, query_type: str, query_value: str) -> None:
        offset = 0
        page = 1
        while offset < 10_000:
            request_key = f"freehire|{query_type}|{query_value}|{offset}"
            if request_key in self.completed_requests:
                offset += FREEHIRE_RESULTS_PER_PAGE
                page += 1
                continue

            params: dict[str, Any] = {
                "countries": "IN",
                "posted_within_days": POSTED_WITHIN_DAYS,
                "limit": FREEHIRE_RESULTS_PER_PAGE,
                "offset": offset,
                "sort": "posted_at",
                "order": "desc",
            }
            if query_type == "category":
                params["category"] = query_value
            else:
                params["q"] = query_value

            payload, elapsed = self._request_json(FREEHIRE_SEARCH_URL, params)
            meta = payload.get("meta") or {}
            ignored = meta.get("ignored_params") or []
            if ignored:
                raise RuntimeError(
                    f"Freehire ignored parameters for {query_type}={query_value}: {ignored}"
                )
            raw_rows = payload.get("data") or []
            collected_at = utc_now()
            normalized = [
                normalize_freehire(item, query_value, page, collected_at)
                for item in raw_rows
                if str(item.get("public_slug") or item.get("external_id") or "").strip()
            ]
            accepted = [row for row in normalized if created_in_window(row["created"])]
            self._append_records(accepted)
            self._record_page(
                request_key=request_key,
                api_source="Freehire",
                query_type=query_type,
                query_value=query_value,
                search_location="India",
                page=page,
                reported_total=meta.get("total"),
                returned=len(raw_rows),
                accepted=len(accepted),
                outside_window=len(normalized) - len(accepted),
                elapsed=elapsed,
                ignored_params=ignored,
            )
            print(
                f"  {query_type}={query_value!r}: offset {offset}, rows {len(raw_rows)}"
            )
            total = int(meta.get("total") or 0)
            if not raw_rows or offset + len(raw_rows) >= total:
                break
            offset += FREEHIRE_RESULTS_PER_PAGE
            page += 1

    def collect_freehire(self) -> None:
        print("\nCollecting Freehire")
        for category in FREEHIRE_CATEGORIES:
            self._collect_freehire_query("category", category)
        for term in FREEHIRE_SEARCH_TERMS:
            self._collect_freehire_query("search_term", term)

    def collect_jooble(self, api_key: str) -> None:
        print("\nCollecting Jooble")
        for term, location, page_limit in JOOBLE_QUERY_PLAN:
            for page in range(1, page_limit + 1):
                request_key = f"jooble|{term}|{location}|{page}"
                if request_key in self.completed_requests:
                    continue

                payload, elapsed = self._request_json_post(
                    f"{JOOBLE_API_ROOT}/{api_key}",
                    {
                        "keywords": term,
                        "location": location,
                        "page": str(page),
                        "ResultOnPage": str(JOOBLE_RESULTS_PER_PAGE),
                        "SearchMode": "1",
                        "companysearch": False,
                    },
                )
                raw_rows = payload.get("jobs") or []
                collected_at = utc_now()
                normalized = [
                    normalize_jooble(item, term, page, collected_at, location)
                    for item in raw_rows
                    if str(item.get("id") or "").strip()
                ]
                accepted = [
                    row for row in normalized if created_in_window(row["created"])
                ]
                self._append_records(accepted)
                self._record_page(
                    request_key=request_key,
                    api_source="Jooble",
                    query_type="search_term",
                    query_value=term,
                    search_location=location,
                    page=page,
                    reported_total=payload.get("totalCount"),
                    returned=len(raw_rows),
                    accepted=len(accepted),
                    outside_window=len(normalized) - len(accepted),
                    elapsed=elapsed,
                )
                print(f"  {term!r} in {location!r}: page {page}, rows {len(raw_rows)}")
                total = int(payload.get("totalCount") or 0)
                if not raw_rows or page * JOOBLE_RESULTS_PER_PAGE >= total:
                    break

    def collect_jsearch(self, api_key: str) -> None:
        print("\nCollecting JSearch")
        for term, location in JSEARCH_QUERY_PLAN:
            page = 1
            request_key = f"jsearch|{term}|{location}|{page}"
            if request_key in self.completed_requests:
                continue

            payload, elapsed = self._request_json(
                JSEARCH_API_ROOT,
                {
                    "query": f"{term} jobs in {location}, India",
                    "country": "in",
                    "language": "en",
                    "date_posted": "all",
                    "num_pages": JSEARCH_NUM_PAGES,
                },
                headers={"x-api-key": api_key},
            )
            data = payload.get("data") or {}
            raw_rows = data.get("jobs") or []
            collected_at = utc_now()
            normalized = [
                normalize_jsearch(item, term, location, collected_at)
                for item in raw_rows
                if str(item.get("job_id") or item.get("job_uid") or "").strip()
            ]
            accepted = [row for row in normalized if created_in_window(row["created"])]
            self._append_records(accepted)
            self._record_page(
                request_key=request_key,
                api_source="JSearch",
                query_type="search_term",
                query_value=term,
                search_location=location,
                page=page,
                reported_total=None,
                returned=len(raw_rows),
                accepted=len(accepted),
                outside_window=len(normalized) - len(accepted),
                elapsed=elapsed,
            )
            print(
                f"  {term!r} in {location!r}: "
                f"rows {len(raw_rows)}, accepted {len(accepted)}"
            )

    def finalize(self) -> dict[str, Any]:
        """Merge checkpoint rows into the raw CSV without loading it into RAM."""

        def merge_terms(*values: Any) -> str:
            terms: list[str] = []
            for value in values:
                for term in str(value or "").split("|"):
                    term = term.strip()
                    if term and term not in terms:
                        terms.append(term)
            return "|".join(terms)

        # The checkpoint is intentionally much smaller than the historical raw
        # file. Keeping only one newest row per source ID bounds memory use to
        # the current collection run rather than the entire 200+ MB snapshot.
        new_records: dict[str, dict[str, Any]] = {}
        if CHECKPOINT_ROWS_FILE.exists():
            with CHECKPOINT_ROWS_FILE.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not created_in_window(record.get("created")):
                        continue
                    key = str(
                        record.get("source_job_key") or record.get("job_id") or ""
                    ).strip()
                    if not key:
                        raise RuntimeError(
                            "Checkpoint row is missing its source job key."
                        )
                    previous = new_records.get(key)
                    if previous is None:
                        record["matched_search_terms"] = merge_terms(
                            record.get("matched_search_terms"),
                            record.get("search_term"),
                        )
                        new_records[key] = record
                        continue
                    combined_terms = merge_terms(
                        previous.get("matched_search_terms"),
                        record.get("matched_search_terms"),
                        record.get("search_term"),
                    )
                    previous_collected = str(previous.get("collected_at_utc") or "")
                    current_collected = str(record.get("collected_at_utc") or "")
                    if current_collected >= previous_collected:
                        record["matched_search_terms"] = combined_terms
                        new_records[key] = record
                    else:
                        previous["matched_search_terms"] = combined_terms

        if not self.existing_raw_available and not new_records:
            raise RuntimeError("No API records were collected.")

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        temporary_raw_file = RAW_FILE.with_suffix(".tmp.csv")
        seen_source_keys: set[str] = set()
        seen_job_ids: set[str] = set()
        source_counts: Counter[str] = Counter()
        country_counts: Counter[str] = Counter()
        description_counts: Counter[str] = Counter()
        date_basis_counts: Counter[str] = Counter()
        row_count = 0
        earliest_created: pd.Timestamp | None = None
        latest_created: pd.Timestamp | None = None

        def prepare_row(record: dict[str, Any]) -> tuple[dict[str, Any], pd.Timestamp]:
            row = {
                column: "" if record.get(column) is None else record.get(column, "")
                for column in RAW_COLUMNS
            }
            job_id = str(row["job_id"] or "").strip()
            source_key = str(row["source_job_key"] or job_id).strip()
            if not job_id or not source_key:
                raise RuntimeError("Final raw snapshot contains a missing job ID.")
            if job_id in seen_job_ids or source_key in seen_source_keys:
                raise RuntimeError(
                    f"Final raw snapshot contains duplicate job ID: {job_id}"
                )
            created = pd.to_datetime(row["created"], errors="coerce", utc=True)
            if pd.isna(created) or not (WINDOW_START <= created <= WINDOW_END):
                raise RuntimeError(
                    f"Final raw snapshot contains an invalid date for {job_id}."
                )
            row["source_job_key"] = source_key
            return row, created

        def write_row(writer: csv.DictWriter, record: dict[str, Any]) -> None:
            nonlocal row_count, earliest_created, latest_created
            row, created = prepare_row(record)
            writer.writerow(row)
            job_id = str(row["job_id"])
            source_key = str(row["source_job_key"])
            seen_job_ids.add(job_id)
            seen_source_keys.add(source_key)
            row_count += 1
            source_counts[str(row["api_source"] or "(missing)")] += 1
            country_counts[str(row["country_validation"] or "(missing)")] += 1
            description_counts[str(row["description_type"] or "(missing)")] += 1
            date_basis_counts[str(row["posting_date_basis"] or "(missing)")] += 1
            earliest_created = (
                created if earliest_created is None else min(earliest_created, created)
            )
            latest_created = (
                created if latest_created is None else max(latest_created, created)
            )

        with temporary_raw_file.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(
                target, fieldnames=RAW_COLUMNS, extrasaction="ignore"
            )
            writer.writeheader()

            if self.existing_raw_available:
                with RAW_FILE.open("r", encoding="utf-8-sig", newline="") as source:
                    for existing in csv.DictReader(source):
                        existing_key = str(
                            existing.get("source_job_key")
                            or existing.get("job_id")
                            or ""
                        ).strip()
                        if existing_key in new_records:
                            new_records[existing_key]["matched_search_terms"] = (
                                merge_terms(
                                    existing.get("matched_search_terms"),
                                    existing.get("search_term"),
                                    new_records[existing_key].get(
                                        "matched_search_terms"
                                    ),
                                )
                            )
                            continue
                        if created_in_window(existing.get("created")):
                            write_row(writer, existing)

            for record in new_records.values():
                write_row(writer, record)

        if row_count == 0:
            temporary_raw_file.unlink(missing_ok=True)
            raise RuntimeError("No in-window API records were collected.")

        temporary_raw_file.replace(RAW_FILE)

        digest_builder = hashlib.sha256()
        with RAW_FILE.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest_builder.update(chunk)
        digest = digest_builder.hexdigest().upper()
        manifest = {
            "snapshot_id": SNAPSHOT_ID,
            "window_start": WINDOW_START.isoformat(),
            "window_end": WINDOW_END.isoformat(),
            "collection_completed_at_utc": utc_now(),
            "raw_file": RAW_FILE.name,
            "sha256": digest,
            "rows": row_count,
            "unique_job_ids": row_count,
            "duplicate_job_ids": 0,
            "earliest_created": (
                earliest_created.isoformat() if earliest_created else None
            ),
            "latest_created": latest_created.isoformat() if latest_created else None,
            "source_counts": dict(source_counts),
            "country_validation_counts": dict(country_counts),
            "description_type_counts": dict(description_counts),
            "posting_date_basis_counts": dict(date_basis_counts),
            "methodology_note": (
                "Live-listing API collection completed across 29-30 Aug 2026 with a defined "
                "analysis cutoff of 29 Aug 2026. Older postings that closed before collection "
                "cannot be observed. Adzuna and Jooble descriptions are snippets; Freehire "
                "and JSearch descriptions are fuller source text. Jooble exposes an updated timestamp "
                "rather than an original posting timestamp, so Jooble rows are excluded from "
                "posting-date trend and posting-age analysis."
            ),
        }
        COLLECTION_MANIFEST_FILE.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        CHECKPOINT_ROWS_FILE.unlink(missing_ok=True)
        CHECKPOINT_STATE_FILE.unlink(missing_ok=True)
        return {
            "rows": row_count,
            "source_counts": dict(source_counts),
            "country_validation_counts": dict(country_counts),
            "description_type_counts": dict(description_counts),
            "posting_date_basis_counts": dict(date_basis_counts),
            "sha256": digest,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=("adzuna", "freehire", "jooble", "jsearch"),
        default=("adzuna", "freehire", "jooble", "jsearch"),
        help="API sources to collect. Existing raw records are always preserved.",
    )
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="Merge successfully checkpointed pages without making API requests.",
    )
    args = parser.parse_args()
    selected_sources = set() if args.finalize_only else set(args.sources)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    jooble_key = os.getenv("JOOBLE_API_KEY", "").strip()
    jsearch_key = os.getenv("JSEARCH_API_KEY", "").strip()
    if "adzuna" in selected_sources and (not app_id or not app_key):
        raise RuntimeError(
            "ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in the current terminal."
        )
    if "jooble" in selected_sources and not jooble_key:
        raise RuntimeError("JOOBLE_API_KEY must be set in the current terminal.")
    if "jsearch" in selected_sources and not jsearch_key:
        raise RuntimeError("JSEARCH_API_KEY must be set in the current terminal.")

    print(f"Collection window: {WINDOW_START.isoformat()} to {WINDOW_END.isoformat()}")
    print(f"Snapshot: {SNAPSHOT_ID}")
    selected_label = (
        ", ".join(sorted(selected_sources)) or "none (finalize checkpoint only)"
    )
    print(f"Selected sources: {selected_label}")
    collector = Collector()
    if "adzuna" in selected_sources:
        collector.collect_adzuna(app_id, app_key)
    if "freehire" in selected_sources:
        collector.collect_freehire()
    if "jooble" in selected_sources:
        collector.collect_jooble(jooble_key)
    if "jsearch" in selected_sources:
        collector.collect_jsearch(jsearch_key)
    summary = collector.finalize()
    source_counts = summary["source_counts"]
    country_counts = summary["country_validation_counts"]

    print("\nCOLLECTION COMPLETE")
    print(f"Unique source jobs: {summary['rows']:,}")
    print(f"Adzuna: {source_counts.get('Adzuna', 0):,}")
    print(f"Freehire: {source_counts.get('Freehire', 0):,}")
    print(f"Jooble: {source_counts.get('Jooble', 0):,}")
    print(f"JSearch: {source_counts.get('JSearch', 0):,}")
    print(f"Confirmed India: {country_counts.get('confirmed', 0):,}")
    print(f"Ambiguous geography: {country_counts.get('ambiguous', 0):,}")
    print(f"Raw file: {RAW_FILE}")


if __name__ == "__main__":
    main()
