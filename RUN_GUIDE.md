# Run guide

## Environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

API credentials are read from environment variables by `scripts/collect_jobs.py`; keep them outside the repository.

## Validate the submitted dataset

```bash
python scripts/validate_analysis.py
python scripts/profile_final_dataset.py
python scripts/build_report_outputs.py
python -m unittest discover -s tests -v
```

`validate_analysis.py` is the release gate. It checks file hashes, row counts, keys, report-table reconciliation, skill coverage, dates, salary eligibility, source mix, dashboard visuals, semantic-model measures, row-level PBIX-to-CSV fidelity, static previews, and the headline findings. The dataset is ready for reporting only when it prints `status: PASS`.

The supplied CSVs are the validated 30 August 2026 freeze. A new collection requires API credentials and will produce a different snapshot:

```bash
python scripts/collect_jobs.py
python scripts/build_analytical_dataset.py
python scripts/validate_analysis.py
```

The full rebuild also creates `reports/exclusion_reason_summary.csv` and `reports/taxonomy_validation_sample.csv`. The submitted portfolio archive does not contain the original raw responses, so those two files will populate on the next authenticated collection run.

To complete the taxonomy spot check, copy the generated sample to `reports/taxonomy_manual_validation.csv`, label every row in `manual_in_scope`, and run:

```bash
python scripts/score_taxonomy_validation.py
```

The scorer writes precision, recall, accuracy, and a separate disagreement file. Do not fill the labels from the model prediction column; they are meant to record an independent human decision.

PostgreSQL is optional. To load the processed tables, configure the connection variables described in `scripts/load_to_postgres.py`, then run that script.

## Reporting

Open `dashboard/DataAnalystJobMarketIntelligence.pbix` to review the five-page report. The packaged model contains the validated snapshot. When refreshing the model, use `data/processed/job_postings_clean.csv` and `data/processed/job_skills_bridge.csv`, then reconcile the report with `dashboard/KPI_EXPECTED_VALUES.md`.
