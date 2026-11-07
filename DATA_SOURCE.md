# Data source and collection notes

## Sources

The freeze combines four public job-search sources:

- Adzuna
- Freehire
- Jooble
- JSearch

Collection was run as a short campaign on 29–30 August 2026. Queries were partitioned by role and city to reduce paging bias, then source identifiers and normalised job fingerprints were used for de-duplication. The source mix in the frozen analytical layer is Freehire 2,407, Jooble 1,572, Adzuna 1,143, and JSearch 338 postings.

## Date handling

The analysis window is 1 January–29 August 2026. Jooble contributes 1,572 rows whose only available timestamp is an updated-date proxy; those rows are retained for full-sample counts but flagged with `posting_date_basis = source_updated_at_proxy` and excluded from observed-date trend comparisons. The remaining 3,888 rows use a source-posted timestamp.

Every processed row has a usable `posted_date` and `created_at` fallback. The final consistency check explicitly verifies that no row has both dates missing.

## Scope and quality decisions

- Role families are assigned with the frozen taxonomy in `scripts/build_analytical_dataset.py`.
- Placeholder locations are retained for full-sample counts but excluded from the specific-city KPI.
- Skills are counted at the distinct-job level; a job with several skill mentions contributes once to each skill.
- Salary analysis uses only rows that pass the documented normalisation and eligibility rules. It is not representative of the full market because only 92 postings disclose an eligible salary.
- Cross-source duplicates are resolved before the final 5,460-job table. The freeze log records 104,079 raw rows, 98,259 exclusions, and 360 cross-source duplicate matches.

Skill extraction coverage differs sharply by source: Freehire 93.19% and JSearch 94.08%, compared with Adzuna 28.78% and Jooble 31.36%. Description length and availability vary across the APIs, which gives Freehire and JSearch more influence over the skill ranking. A sensitivity check restricted to those two high-coverage sources returned the same top ten skills in the same order. Source counts are available in `reports/skill_coverage_report.csv`.

Skills are extracted with a curated 44-term keyword and regular-expression dictionary applied to titles and descriptions. The method can miss synonyms, non-English wording, and skills outside the dictionary. It can also count a negated phrase such as “SQL not required.” The 61.96% tagging rate is therefore best read as measured keyword coverage rather than complete skill coverage.

## Role-taxonomy review

The build script prepares a balanced 100-row review sheet with 50 retained roles and 50 taxonomy exclusions. Manual judgment is intentionally kept separate from the model output: copy `reports/taxonomy_validation_sample.csv` to `reports/taxonomy_manual_validation.csv`, complete `manual_in_scope`, and run `scripts/score_taxonomy_validation.py`. Precision and recall should only be reported after that human review is finished.

Job descriptions were used during feature extraction but are not included in the submitted CSV. The `description_type` value `not_included` makes that omission explicit; the extracted role, experience, and skill fields are retained.
