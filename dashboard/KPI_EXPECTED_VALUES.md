# Power BI reconciliation sheet

Build the KPI row with numeric Card (123) visuals. The values below are the expected full-sample results from the frozen processed tables; do not hard-code them in the report.

| Card title | Measure logic | Expected value |
| --- | --- | ---: |
| Total Analyst Jobs | distinct `job_id` | 5,460 |
| Unique Companies | distinct non-placeholder `company_name` | 1,941 |
| Specific-City Locations | distinct non-null `specific_city` | 114 |
| Skill-Tagged Jobs | jobs with at least one bridge row | 3,383 |
| Salary-Tagged Jobs | `salary_analysis_eligible = true` | 92 |
| Median Salary (₹L) | median eligible `salary_midpoint` / 100,000 | 13.75 |

Coverage references: skill tagging 61.96%, salary coverage 1.68%, and explicit experience coverage 45.37%.

Reconciliation findings: Data Analyst 1,946; SQL 1,801; Bengaluru 1,628; SQL salary n=43 with median ₹16.50L; non-SQL n=49 with median ₹7.50L; observed difference ₹9.00L and bootstrap 95% CI ₹2.50L–₹12.50L. The salary comparison is descriptive.

## Remaining page cards

| Page | Card | Expected value |
| --- | --- | ---: |
| Skills & Experience | Skill-Tagged Jobs | 3,383 |
| Skills & Experience | Unique Skills | 44 |
| Skills & Experience | Job-Skill Rows | 13,122 |
| Skills & Experience | Skill Coverage | 61.96% |
| Skills & Experience | Experience-Labeled Jobs | 2,477 |
| Skills & Experience | Experience Coverage | 45.37% |
| Salary Insights | Salary-Tagged Jobs | 92 |
| Salary Insights | Salary Coverage | 1.68% |
| Salary Insights | Median Salary | ₹13.75L |
| Salary Insights | Mean Salary | ₹14.51L |
| Salary Insights | P25 Salary | ₹6.34L |
| Salary Insights | P75 Salary | ₹20.00L |
| Role & Location | Specific-City Vacancies | 4,725 |
| Role & Location | Specific-City Locations | 114 |
| Role & Location | Unique Companies | 1,941 |
| Role & Location | Top-5 Employer Jobs | 448 |
| Role & Location | Top-5 Employer Share | 8.21% |
| Role & Location | Total Analyst Jobs | 5,460 |
| Trends & Statistical | Recent 90-Day Jobs | 3,506 |
| Trends & Statistical | Complete Weeks | 33 |
| Trends & Statistical | Complete-Week Jobs | 3,268 |
| Trends & Statistical | SQL Salary Observations | 43 |
| Trends & Statistical | Observed SQL Median Difference | ₹9.00L |
| Trends & Statistical | Bootstrap Iterations | 50,000 |
