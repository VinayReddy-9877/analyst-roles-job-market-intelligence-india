/*
Data Analyst Job Market Intelligence: Skill, Experience & Salary Analytics — India

PostgreSQL analytical queries

Database: job_market
Schema:   job_market

Analytical grain
----------------
fact_jobs: one analytical vacancy
bridge_job_skill: one vacancy-skill relationship

Reporting rules
---------------
1. Missing salary values are not imputed.
2. Salary analysis uses salary_analysis_eligible = TRUE.
3. Salary by role and city requires at least 30 salary observations.
4. Skill salary analysis is exploratory and requires at least 10 observations.
5. Experience salary analysis requires at least 20 observations.
6. Skill co-occurrence counts distinct vacancies containing both skills.
7. Weekly trend analysis uses complete Monday-Sunday weeks only.
8. Weekly slopes summarize the captured window; no forecasting model is fitted.
9. Salary comparisons use SQL / other-tagged / unknown skill evidence; they do not estimate a pay impact.
10. Dated period comparisons exclude postings without an observed posting date.
11. Skill trends from different collection sources are not direct market forecasts.
*/

SET search_path TO job_market, public;


/* ============================================================
   0. DATASET OVERVIEW
   ============================================================ */

SELECT
    COUNT(*) AS unique_vacancies,
    COUNT(DISTINCT company_key) AS unique_companies,
    COUNT(DISTINCT location_key) AS unique_locations,
    COUNT(DISTINCT role_key) AS role_families,

    COUNT(*) FILTER (
        WHERE has_extracted_skill
    ) AS skill_tagged_jobs,

    ROUND(
        100.0
        * COUNT(*) FILTER (
            WHERE has_extracted_skill
        )
        / NULLIF(COUNT(*), 0),
        2
    ) AS skill_coverage_pct,

    COUNT(*) FILTER (
        WHERE experience_min_years IS NOT NULL
    ) AS experience_labeled_jobs,

    ROUND(
        100.0
        * COUNT(*) FILTER (
            WHERE experience_min_years IS NOT NULL
        )
        / NULLIF(COUNT(*), 0),
        2
    ) AS experience_coverage_pct,

    COUNT(*) FILTER (
        WHERE has_salary_source
    ) AS salary_source_jobs,

    ROUND(
        100.0
        * COUNT(*) FILTER (
            WHERE has_salary_source
        )
        / NULLIF(COUNT(*), 0),
        2
    ) AS salary_source_coverage_pct,

    COUNT(*) FILTER (
        WHERE salary_analysis_eligible
    ) AS salary_analysis_jobs,

    ROUND(
        100.0
        * COUNT(*) FILTER (
            WHERE salary_analysis_eligible
        )
        / NULLIF(COUNT(*), 0),
        2
    ) AS salary_analysis_coverage_pct,

    COUNT(*) FILTER (
        WHERE is_recent_90d
    ) AS recent_90d_jobs,

    COUNT(*) FILTER (
        WHERE is_complete_week
    ) AS complete_week_jobs

FROM fact_jobs;


/* Date quality: preserve proxy-dated records in totals, not trends */
SELECT
    COUNT(*) FILTER (
        WHERE is_posting_date_observed AND is_recent_90d
    ) AS recent_observed_jobs,
    COUNT(*) FILTER (
        WHERE is_posting_date_observed AND NOT is_recent_90d
    ) AS earlier_observed_jobs,
    COUNT(*) FILTER (
        WHERE NOT is_posting_date_observed
    ) AS proxy_dated_jobs,
    COUNT(*) AS total_jobs
FROM fact_jobs;


/* Database row-count audit */
SELECT
    (SELECT COUNT(*) FROM fact_jobs) AS fact_jobs,
    (SELECT COUNT(*) FROM bridge_job_skill) AS job_skill_rows,
    (SELECT COUNT(*) FROM dim_skill) AS unique_skills,
    (
        SELECT COUNT(*)
        FROM fact_jobs
        WHERE salary_analysis_eligible
    ) AS salary_analysis_rows;


/* Source provenance */
SELECT
    source_family,
    source_provider,
    COUNT(*) AS job_count,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS share_pct
FROM fact_jobs
GROUP BY
    source_family,
    source_provider
ORDER BY
    job_count DESC,
    source_family,
    source_provider;


/* Salary normalization audit */
SELECT
    COALESCE(
        salary_normalization_status,
        'No Salary Source'
    ) AS salary_status,
    COUNT(*) AS job_count,
    COUNT(*) FILTER (
        WHERE salary_analysis_eligible
    ) AS salary_analysis_jobs,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        2
    ) AS share_pct
FROM fact_jobs
GROUP BY
    COALESCE(
        salary_normalization_status,
        'No Salary Source'
    )
ORDER BY
    job_count DESC,
    salary_status;


/* ============================================================
   1. ROLE DEMAND
   ============================================================ */

WITH role_counts AS (
    SELECT
        r.role_family,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_role AS r
        ON f.role_key = r.role_key
    GROUP BY
        r.role_family
),
role_distribution AS (
    SELECT
        role_family,
        job_count,
        100.0 * job_count
            / NULLIF(
                SUM(job_count) OVER (),
                0
            ) AS market_share_pct
    FROM role_counts
)
SELECT
    role_family,
    job_count,
    ROUND(
        market_share_pct,
        2
    ) AS market_share_pct,

    ROUND(
        SUM(market_share_pct) OVER (
            ORDER BY
                job_count DESC,
                role_family
            ROWS BETWEEN
                UNBOUNDED PRECEDING
                AND CURRENT ROW
        ),
        2
    ) AS cumulative_market_share_pct,

    DENSE_RANK() OVER (
        ORDER BY job_count DESC
    ) AS demand_rank

FROM role_distribution
ORDER BY
    job_count DESC,
    role_family;


/* Recent 90-day role mix */
WITH recent_role_counts AS (
    SELECT
        r.role_family,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_role AS r
        ON f.role_key = r.role_key
    WHERE f.is_recent_90d
    GROUP BY
        r.role_family
)
SELECT
    role_family,
    job_count,
    ROUND(
        100.0 * job_count
        / NULLIF(
            SUM(job_count) OVER (),
            0
        ),
        2
    ) AS recent_market_share_pct,
    DENSE_RANK() OVER (
        ORDER BY job_count DESC
    ) AS recent_demand_rank
FROM recent_role_counts
ORDER BY
    job_count DESC,
    role_family;


/* ============================================================
   2. LOCATION DEMAND
   ============================================================ */

/* Location-scope distribution */
SELECT
    l.location_scope,
    COUNT(*) AS job_count,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(
            SUM(COUNT(*)) OVER (),
            0
        ),
        2
    ) AS share_pct
FROM fact_jobs AS f
JOIN dim_location AS l
    ON f.location_key = l.location_key
GROUP BY
    l.location_scope
ORDER BY
    job_count DESC,
    l.location_scope;


/* Specific-city demand */
WITH city_counts AS (
    SELECT
        l.city,
        l.state,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_location AS l
        ON f.location_key = l.location_key
    WHERE l.location_scope = 'Specific City'
      AND LOWER(TRIM(l.city)) NOT IN (
          'unknown', 'any', 'in', 'india', 'india - hq',
          'maharashtra', 'telangana', 'karnataka', 'gujarat',
          'haryana', 'uttar pradesh', 'california', 'barcelona'
      )
    GROUP BY
        l.city,
        l.state
)
SELECT
    city,
    state,
    job_count,
    ROUND(
        100.0 * job_count
        / NULLIF(
            SUM(job_count) OVER (),
            0
        ),
        2
    ) AS share_of_specific_city_jobs_pct,
    DENSE_RANK() OVER (
        ORDER BY job_count DESC
    ) AS city_demand_rank
FROM city_counts
ORDER BY
    job_count DESC,
    city;


/* ============================================================
   3. EMPLOYER DEMAND AND CONCENTRATION
   ============================================================ */

WITH employer_counts AS (
    SELECT
        c.company_name,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_company AS c
        ON f.company_key = c.company_key
    WHERE c.company_name <> 'Unknown Company'
    GROUP BY
        c.company_name
)
SELECT
    company_name,
    job_count,
    ROUND(
        100.0 * job_count
        / NULLIF(
            SUM(job_count) OVER (),
            0
        ),
        2
    ) AS employer_share_pct,
    DENSE_RANK() OVER (
        ORDER BY job_count DESC
    ) AS employer_rank
FROM employer_counts
ORDER BY
    job_count DESC,
    company_name
LIMIT 25;


/* Top-five employer concentration */
WITH employer_counts AS (
    SELECT
        c.company_name,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_company AS c
        ON f.company_key = c.company_key
    WHERE c.company_name <> 'Unknown Company'
    GROUP BY
        c.company_name
),
ranked AS (
    SELECT
        company_name,
        job_count,
        ROW_NUMBER() OVER (
            ORDER BY
                job_count DESC,
                company_name
        ) AS employer_position
    FROM employer_counts
)
SELECT
    SUM(job_count) FILTER (
        WHERE employer_position <= 5
    ) AS top_5_job_count,

    SUM(job_count) AS known_employer_job_count,

    ROUND(
        100.0
        * SUM(job_count) FILTER (
            WHERE employer_position <= 5
        )
        / NULLIF(
            SUM(job_count),
            0
        ),
        2
    ) AS top_5_employer_share_pct
FROM ranked;


/* ============================================================
   4. WORK MODE
   ============================================================ */

SELECT
    work_mode,
    COUNT(*) AS job_count,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(
            SUM(COUNT(*)) OVER (),
            0
        ),
        2
    ) AS share_pct
FROM fact_jobs
GROUP BY
    work_mode
ORDER BY
    job_count DESC,
    work_mode;


/* ============================================================
   5. EXPERIENCE DEMAND
   ============================================================ */

SELECT
    experience_band,
    COUNT(*) AS job_count,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(
            SUM(COUNT(*)) OVER (),
            0
        ),
        2
    ) AS share_pct
FROM fact_jobs
GROUP BY
    experience_band
ORDER BY
    CASE experience_band
        WHEN '0–1' THEN 1
        WHEN '1–2' THEN 2
        WHEN '2–3' THEN 3
        WHEN '3–4' THEN 4
        WHEN '4–5' THEN 5
        WHEN '5–6' THEN 6
        WHEN '6–7' THEN 7
        WHEN '7–8' THEN 8
        WHEN '8–9' THEN 9
        WHEN '9–10' THEN 10
        WHEN '10–15' THEN 11
        WHEN '15+' THEN 12
        WHEN 'Not Specified' THEN 13
        ELSE 14
    END;


/* Experience mix by role */
SELECT
    r.role_family,
    f.experience_band,
    COUNT(*) AS job_count,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(
            SUM(COUNT(*)) OVER (
                PARTITION BY r.role_family
            ),
            0
        ),
        2
    ) AS role_experience_share_pct
FROM fact_jobs AS f
JOIN dim_role AS r
    ON f.role_key = r.role_key
GROUP BY
    r.role_family,
    f.experience_band
ORDER BY
    r.role_family,
    job_count DESC,
    f.experience_band;


/* ============================================================
   6. SKILL DEMAND
   ============================================================ */

WITH skill_counts AS (
    SELECT
        s.skill,
        s.skill_category,
        COUNT(DISTINCT b.job_key) AS job_count
    FROM bridge_job_skill AS b
    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key
    GROUP BY
        s.skill,
        s.skill_category
),
totals AS (
    SELECT
        COUNT(*) AS total_jobs,
        COUNT(*) FILTER (
            WHERE has_extracted_skill
        ) AS skill_tagged_jobs
    FROM fact_jobs
)
SELECT
    sc.skill,
    sc.skill_category,
    sc.job_count,

    ROUND(
        100.0 * sc.job_count
        / NULLIF(
            t.total_jobs,
            0
        ),
        2
    ) AS share_of_all_jobs_pct,

    ROUND(
        100.0 * sc.job_count
        / NULLIF(
            t.skill_tagged_jobs,
            0
        ),
        2
    ) AS share_of_skill_tagged_jobs_pct,

    DENSE_RANK() OVER (
        ORDER BY sc.job_count DESC
    ) AS skill_demand_rank

FROM skill_counts AS sc
CROSS JOIN totals AS t
ORDER BY
    sc.job_count DESC,
    sc.skill;


/* Recent 90-day skill demand */
WITH recent_skill_counts AS (
    SELECT
        s.skill,
        s.skill_category,
        COUNT(DISTINCT f.job_key) AS job_count
    FROM fact_jobs AS f
    JOIN bridge_job_skill AS b
        ON f.job_key = b.job_key
    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key
    WHERE f.is_recent_90d
    GROUP BY
        s.skill,
        s.skill_category
),
recent_total AS (
    SELECT
        COUNT(*) AS recent_jobs
    FROM fact_jobs
    WHERE is_recent_90d
)
SELECT
    r.skill,
    r.skill_category,
    r.job_count,
    ROUND(
        100.0 * r.job_count
        / NULLIF(
            t.recent_jobs,
            0
        ),
        2
    ) AS recent_job_share_pct
FROM recent_skill_counts AS r
CROSS JOIN recent_total AS t
ORDER BY
    r.job_count DESC,
    r.skill;


/* ============================================================
   7. SKILL CO-OCCURRENCE
   ============================================================ */

WITH skill_pairs AS (
    SELECT
        b1.job_key,
        s1.skill AS skill_1,
        s2.skill AS skill_2
    FROM bridge_job_skill AS b1

    JOIN bridge_job_skill AS b2
        ON b1.job_key = b2.job_key
       AND b1.skill_key < b2.skill_key

    JOIN dim_skill AS s1
        ON b1.skill_key = s1.skill_key

    JOIN dim_skill AS s2
        ON b2.skill_key = s2.skill_key
)
SELECT
    skill_1,
    skill_2,
    COUNT(DISTINCT job_key) AS jobs_with_pair
FROM skill_pairs
GROUP BY
    skill_1,
    skill_2
ORDER BY
    jobs_with_pair DESC,
    skill_1,
    skill_2
LIMIT 50;


/* Co-occurrence rate among jobs containing the first skill */
WITH skill_counts AS (
    SELECT
        s.skill,
        COUNT(DISTINCT b.job_key) AS skill_jobs
    FROM bridge_job_skill AS b
    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key
    GROUP BY
        s.skill
),
pairs AS (
    SELECT
        s1.skill AS skill_1,
        s2.skill AS skill_2,
        COUNT(DISTINCT b1.job_key) AS pair_jobs
    FROM bridge_job_skill AS b1

    JOIN bridge_job_skill AS b2
        ON b1.job_key = b2.job_key
       AND b1.skill_key <> b2.skill_key

    JOIN dim_skill AS s1
        ON b1.skill_key = s1.skill_key

    JOIN dim_skill AS s2
        ON b2.skill_key = s2.skill_key

    GROUP BY
        s1.skill,
        s2.skill
)
SELECT
    p.skill_1,
    p.skill_2,
    p.pair_jobs,
    sc.skill_jobs AS skill_1_jobs,

    ROUND(
        100.0 * p.pair_jobs
        / NULLIF(
            sc.skill_jobs,
            0
        ),
        2
    ) AS cooccurrence_rate_pct

FROM pairs AS p
JOIN skill_counts AS sc
    ON p.skill_1 = sc.skill
ORDER BY
    p.pair_jobs DESC,
    p.skill_1,
    p.skill_2
LIMIT 50;


/* ============================================================
   8. OVERALL SALARY DISTRIBUTION
   ============================================================ */

SELECT
    COUNT(*) AS salary_n,

    ROUND(
        PERCENTILE_CONT(0.25)
        WITHIN GROUP (
            ORDER BY salary_midpoint
        )::NUMERIC,
        2
    ) AS salary_p25_inr,

    ROUND(
        PERCENTILE_CONT(0.50)
        WITHIN GROUP (
            ORDER BY salary_midpoint
        )::NUMERIC,
        2
    ) AS median_salary_inr,

    ROUND(
        AVG(salary_midpoint),
        2
    ) AS mean_salary_inr,

    ROUND(
        PERCENTILE_CONT(0.75)
        WITHIN GROUP (
            ORDER BY salary_midpoint
        )::NUMERIC,
        2
    ) AS salary_p75_inr,

    ROUND(
        MIN(salary_midpoint),
        2
    ) AS minimum_salary_inr,

    ROUND(
        MAX(salary_midpoint),
        2
    ) AS maximum_salary_inr,

    COUNT(*) FILTER (
        WHERE salary_midpoint >= 3000000
    ) AS jobs_at_or_above_30_lakh

FROM fact_jobs
WHERE salary_analysis_eligible;


/* ============================================================
   9. SALARY BY ROLE
   Minimum sample: n >= 30
   ============================================================ */

WITH role_salary AS (
    SELECT
        r.role_family,
        COUNT(*) AS salary_n,

        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY f.salary_midpoint
        ) AS median_salary,

        AVG(
            f.salary_midpoint
        ) AS mean_salary

    FROM fact_jobs AS f
    JOIN dim_role AS r
        ON f.role_key = r.role_key

    WHERE f.salary_analysis_eligible

    GROUP BY
        r.role_family
)
SELECT
    role_family,
    salary_n,
    ROUND(
        median_salary::NUMERIC,
        2
    ) AS median_salary_inr,
    ROUND(
        mean_salary,
        2
    ) AS mean_salary_inr
FROM role_salary
WHERE salary_n >= 30
ORDER BY
    median_salary DESC,
    salary_n DESC,
    role_family;


/* Salary sample-size audit by role */
SELECT
    r.role_family,
    COUNT(*) FILTER (
        WHERE f.salary_analysis_eligible
    ) AS salary_n
FROM fact_jobs AS f
JOIN dim_role AS r
    ON f.role_key = r.role_key
GROUP BY
    r.role_family
ORDER BY
    salary_n DESC,
    r.role_family;


/* ============================================================
   10. SALARY BY CITY
   Minimum sample: n >= 30
   ============================================================ */

WITH city_salary AS (
    SELECT
        l.city,
        l.state,
        COUNT(*) AS salary_n,

        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY f.salary_midpoint
        ) AS median_salary,

        AVG(
            f.salary_midpoint
        ) AS mean_salary

    FROM fact_jobs AS f
    JOIN dim_location AS l
        ON f.location_key = l.location_key

    WHERE f.salary_analysis_eligible
      AND l.location_scope = 'Specific City'

    GROUP BY
        l.city,
        l.state
)
SELECT
    city,
    state,
    salary_n,
    ROUND(
        median_salary::NUMERIC,
        2
    ) AS median_salary_inr,
    ROUND(
        mean_salary,
        2
    ) AS mean_salary_inr
FROM city_salary
WHERE salary_n >= 30
ORDER BY
    median_salary DESC,
    salary_n DESC,
    city;


/* Salary sample-size audit by city */
SELECT
    l.city,
    l.state,
    COUNT(*) FILTER (
        WHERE f.salary_analysis_eligible
    ) AS salary_n
FROM fact_jobs AS f
JOIN dim_location AS l
    ON f.location_key = l.location_key
WHERE l.location_scope = 'Specific City'
GROUP BY
    l.city,
    l.state
ORDER BY
    salary_n DESC,
    l.city;


/* ============================================================
   11. SALARY BY EXPERIENCE
   Minimum sample: n >= 20
   ============================================================ */

WITH experience_salary AS (
    SELECT
        experience_band,
        COUNT(*) AS salary_n,

        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY salary_midpoint
        ) AS median_salary,

        AVG(
            salary_midpoint
        ) AS mean_salary

    FROM fact_jobs

    WHERE salary_analysis_eligible
      AND experience_band <> 'Not Specified'

    GROUP BY
        experience_band
)
SELECT
    experience_band,
    salary_n,
    ROUND(
        median_salary::NUMERIC,
        2
    ) AS median_salary_inr,
    ROUND(
        mean_salary,
        2
    ) AS mean_salary_inr
FROM experience_salary
WHERE salary_n >= 20
ORDER BY
    median_salary DESC,
    salary_n DESC,
    experience_band;


/* Experience salary sample-size audit */
SELECT
    experience_band,
    COUNT(*) FILTER (
        WHERE salary_analysis_eligible
    ) AS salary_n
FROM fact_jobs
GROUP BY
    experience_band
ORDER BY
    salary_n DESC,
    experience_band;


/* ============================================================
   12. EXPLORATORY SKILL SALARY ANALYSIS
   Minimum sample: n >= 10
   ============================================================ */

WITH overall_salary AS (
    SELECT
        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY salary_midpoint
        ) AS overall_median
    FROM fact_jobs
    WHERE salary_analysis_eligible
),
skill_salary AS (
    SELECT
        s.skill,
        COUNT(DISTINCT f.job_key) AS salary_n,

        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY f.salary_midpoint
        ) AS median_salary,

        AVG(
            f.salary_midpoint
        ) AS mean_salary

    FROM fact_jobs AS f

    JOIN bridge_job_skill AS b
        ON f.job_key = b.job_key

    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key

    WHERE f.salary_analysis_eligible

    GROUP BY
        s.skill
)
SELECT
    ss.skill,
    ss.salary_n,

    ROUND(
        ss.median_salary::NUMERIC,
        2
    ) AS median_salary_inr,

    ROUND(
        ss.mean_salary,
        2
    ) AS mean_salary_inr,

    ROUND(
        (
            100.0
            * (
                ss.median_salary
                - os.overall_median
            )
            / NULLIF(
                os.overall_median,
                0
            )
        )::NUMERIC,
        2
    ) AS median_difference_vs_overall_pct

FROM skill_salary AS ss
CROSS JOIN overall_salary AS os

WHERE ss.salary_n >= 10

ORDER BY
    ss.median_salary DESC,
    ss.salary_n DESC,
    ss.skill;


/* Skill salary sample-size audit */
SELECT
    s.skill,
    COUNT(DISTINCT f.job_key) FILTER (
        WHERE f.salary_analysis_eligible
    ) AS salary_n
FROM bridge_job_skill AS b
JOIN dim_skill AS s
    ON b.skill_key = s.skill_key
JOIN fact_jobs AS f
    ON b.job_key = f.job_key
GROUP BY
    s.skill
ORDER BY
    salary_n DESC,
    s.skill;


/* ============================================================
   13. SALARY AND SQL SKILL EVIDENCE
   SQL detected vs other detected skills vs skill information unknown.
   Descriptive only. No causal interpretation or regression here.
   ============================================================ */

WITH salary_jobs AS (
    SELECT
        f.job_key,
        f.source_family,
        f.experience_band,
        f.salary_midpoint,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM bridge_job_skill AS b
                JOIN dim_skill AS s ON s.skill_key = b.skill_key
                WHERE b.job_key = f.job_key AND s.skill = 'SQL'
            ) THEN 'SQL detected'
            WHEN f.has_extracted_skill THEN 'Other skills detected (no SQL)'
            ELSE 'Skill information unknown'
        END AS skill_evidence_group
    FROM fact_jobs AS f
    WHERE f.salary_analysis_eligible
)
SELECT
    skill_evidence_group,
    COUNT(*) AS salary_n,
    ROUND(AVG(salary_midpoint), 2) AS mean_salary_inr,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY salary_midpoint
        )::NUMERIC, 2
    ) AS median_salary_inr,
    ROUND(MIN(salary_midpoint), 2) AS minimum_salary_inr,
    ROUND(MAX(salary_midpoint), 2) AS maximum_salary_inr
FROM salary_jobs
GROUP BY skill_evidence_group
ORDER BY
    CASE skill_evidence_group
        WHEN 'SQL detected' THEN 1
        WHEN 'Other skills detected (no SQL)' THEN 2
        ELSE 3
    END;


/* Same comparison within each source; small groups are descriptive. */
WITH salary_jobs AS (
    SELECT
        f.source_family,
        f.salary_midpoint,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM bridge_job_skill AS b
                JOIN dim_skill AS s ON s.skill_key = b.skill_key
                WHERE b.job_key = f.job_key AND s.skill = 'SQL'
            ) THEN 'SQL detected'
            WHEN f.has_extracted_skill THEN 'Other skills detected (no SQL)'
            ELSE 'Skill information unknown'
        END AS skill_evidence_group
    FROM fact_jobs AS f
    WHERE f.salary_analysis_eligible
)
SELECT
    source_family,
    skill_evidence_group,
    COUNT(*) AS salary_n,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY salary_midpoint
        )::NUMERIC, 2
    ) AS median_salary_inr
FROM salary_jobs
GROUP BY source_family, skill_evidence_group
ORDER BY source_family, skill_evidence_group;


/* Observed median difference uses only SQL vs other KNOWN skills.
   The unknown group is deliberately excluded from this contrast. */
WITH classified AS (
    SELECT
        f.salary_midpoint,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM bridge_job_skill AS b
                JOIN dim_skill AS s ON s.skill_key = b.skill_key
                WHERE b.job_key = f.job_key AND s.skill = 'SQL'
            ) THEN 'SQL detected'
            WHEN f.has_extracted_skill THEN 'Other skills detected (no SQL)'
            ELSE 'Unknown'
        END AS skill_group
    FROM fact_jobs AS f
    WHERE f.salary_analysis_eligible
),
medians AS (
    SELECT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_midpoint)
            FILTER (WHERE skill_group = 'SQL detected') AS sql_median,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_midpoint)
            FILTER (WHERE skill_group = 'Other skills detected (no SQL)') AS other_skills_median
    FROM classified
)
SELECT
    ROUND(sql_median::NUMERIC, 2) AS sql_median_inr,
    ROUND(other_skills_median::NUMERIC, 2) AS other_tagged_median_inr,
    ROUND((sql_median - other_skills_median)::NUMERIC, 2)
        AS observed_median_difference_inr
FROM medians;


/* ============================================================
   14. COMPLETE-WEEK JOB DEMAND
   ============================================================ */

SELECT
    d.week_start,
    COUNT(*) AS weekly_jobs
FROM fact_jobs AS f
JOIN dim_date AS d
    ON f.date_key = d.date_key
WHERE f.is_complete_week
GROUP BY
    d.week_start
ORDER BY
    d.week_start;


/* Week-over-week vacancy movement */
WITH weekly_jobs AS (
    SELECT
        d.week_start,
        COUNT(*) AS weekly_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d
        ON f.date_key = d.date_key
    WHERE f.is_complete_week
    GROUP BY
        d.week_start
),
with_lag AS (
    SELECT
        week_start,
        weekly_jobs,

        LAG(
            weekly_jobs
        ) OVER (
            ORDER BY week_start
        ) AS prior_week_jobs

    FROM weekly_jobs
)
SELECT
    week_start,
    weekly_jobs,
    prior_week_jobs,

    weekly_jobs
        - prior_week_jobs
        AS absolute_change,

    ROUND(
        100.0
        * (
            weekly_jobs
            - prior_week_jobs
        )
        / NULLIF(
            prior_week_jobs,
            0
        ),
        2
    ) AS week_over_week_pct

FROM with_lag
ORDER BY
    week_start;


/* ============================================================
   15. WEEKLY SKILL SHARE
   ============================================================ */

WITH weekly_totals AS (
    SELECT
        d.week_start,
        COUNT(*) AS weekly_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d
        ON f.date_key = d.date_key
    WHERE f.is_complete_week
    GROUP BY
        d.week_start
),
weekly_skill_jobs AS (
    SELECT
        d.week_start,
        s.skill,
        COUNT(DISTINCT f.job_key) AS skill_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d
        ON f.date_key = d.date_key
    JOIN bridge_job_skill AS b
        ON f.job_key = b.job_key
    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key
    WHERE f.is_complete_week
    GROUP BY
        d.week_start,
        s.skill
)
SELECT
    ws.week_start,
    ws.skill,
    ws.skill_jobs,
    wt.weekly_jobs,

    ROUND(
        100.0 * ws.skill_jobs
        / NULLIF(
            wt.weekly_jobs,
            0
        ),
        2
    ) AS weekly_skill_share_pct

FROM weekly_skill_jobs AS ws
JOIN weekly_totals AS wt
    ON ws.week_start = wt.week_start
ORDER BY
    ws.skill,
    ws.week_start;


/* ============================================================
   16. THREE-WEEK ROLLING SKILL SHARE
   ============================================================ */

WITH weekly_totals AS (
    SELECT
        d.week_start,
        COUNT(*) AS weekly_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d
        ON f.date_key = d.date_key
    WHERE f.is_complete_week
    GROUP BY
        d.week_start
),
weekly_skill_jobs AS (
    SELECT
        d.week_start,
        s.skill,
        COUNT(DISTINCT f.job_key) AS skill_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d
        ON f.date_key = d.date_key
    JOIN bridge_job_skill AS b
        ON f.job_key = b.job_key
    JOIN dim_skill AS s
        ON b.skill_key = s.skill_key
    WHERE f.is_complete_week
    GROUP BY
        d.week_start,
        s.skill
),
weekly_share AS (
    SELECT
        ws.week_start,
        ws.skill,

        100.0 * ws.skill_jobs
        / NULLIF(
            wt.weekly_jobs,
            0
        ) AS skill_share_pct

    FROM weekly_skill_jobs AS ws
    JOIN weekly_totals AS wt
        ON ws.week_start = wt.week_start
)
SELECT
    week_start,
    skill,

    ROUND(
        skill_share_pct,
        2
    ) AS weekly_skill_share_pct,

    ROUND(
        AVG(
            skill_share_pct
        ) OVER (
            PARTITION BY skill
            ORDER BY week_start
            ROWS BETWEEN
                2 PRECEDING
                AND CURRENT ROW
        ),
        2
    ) AS rolling_3_week_share_pct

FROM weekly_share
ORDER BY
    skill,
    week_start;


/* ============================================================
   17. DESCRIPTIVE WEEKLY SKILL SHARE SLOPES
   ============================================================ */

WITH tracked_skills(skill) AS (
    VALUES ('SQL'), ('Excel'), ('Power BI'), ('Python'), ('Tableau')
),
weekly_totals AS (
    SELECT d.week_start, COUNT(*) AS weekly_jobs
    FROM fact_jobs AS f
    JOIN dim_date AS d ON d.date_key = f.date_key
    WHERE f.is_complete_week AND f.is_posting_date_observed
    GROUP BY d.week_start
),
weekly_skill_counts AS (
    SELECT d.week_start, s.skill, COUNT(DISTINCT f.job_key) AS jobs_with_skill
    FROM fact_jobs AS f
    JOIN dim_date AS d ON d.date_key = f.date_key
    JOIN bridge_job_skill AS b ON b.job_key = f.job_key
    JOIN dim_skill AS s ON s.skill_key = b.skill_key
    WHERE f.is_complete_week AND f.is_posting_date_observed
      AND s.skill IN ('SQL', 'Excel', 'Power BI', 'Python', 'Tableau')
    GROUP BY d.week_start, s.skill
),
weekly_shares AS (
    SELECT
        wt.week_start,
        t.skill,
        100.0 * COALESCE(wsc.jobs_with_skill, 0)
            / NULLIF(wt.weekly_jobs, 0) AS share_pct
    FROM weekly_totals AS wt
    CROSS JOIN tracked_skills AS t
    LEFT JOIN weekly_skill_counts AS wsc
        ON wsc.week_start = wt.week_start AND wsc.skill = t.skill
),
indexed AS (
    SELECT
        skill,
        week_start,
        share_pct,
        DENSE_RANK() OVER (ORDER BY week_start) - 1 AS week_index
    FROM weekly_shares
)
SELECT
    skill,
    COUNT(*) AS observed_complete_weeks,
    ROUND(REGR_SLOPE(share_pct, week_index)::NUMERIC, 4)
        AS descriptive_pp_change_per_week,
    ROUND(MIN(share_pct)::NUMERIC, 2) AS min_weekly_skill_share_pct,
    ROUND(MAX(share_pct)::NUMERIC, 2) AS max_weekly_skill_share_pct
FROM indexed
GROUP BY skill
ORDER BY descriptive_pp_change_per_week DESC, skill;


/* ============================================================
   18. ROLE MIX BY OBSERVED POSTING PERIOD
   ============================================================ */

WITH period_role_counts AS (
    SELECT
        CASE WHEN f.is_recent_90d
            THEN 'Recent 90 Days' ELSE 'Earlier (Observed)'
        END AS market_period,
        r.role_family,
        COUNT(*) AS job_count
    FROM fact_jobs AS f
    JOIN dim_role AS r ON r.role_key = f.role_key
    WHERE f.is_posting_date_observed
    GROUP BY 1, 2
)
SELECT
    market_period,
    role_family,
    job_count,
    ROUND(
        100.0 * job_count /
        NULLIF(SUM(job_count) OVER (PARTITION BY market_period), 0), 2
    ) AS role_share_pct
FROM period_role_counts
ORDER BY role_family, market_period;


/* ============================================================
   19. SKILL MIX BY OBSERVED POSTING PERIOD
   ============================================================ */

WITH dated_jobs AS (
    SELECT
        job_key,
        CASE WHEN is_recent_90d
            THEN 'Recent 90 Days' ELSE 'Earlier (Observed)'
        END AS market_period
    FROM fact_jobs
    WHERE is_posting_date_observed
),
period_totals AS (
    SELECT market_period, COUNT(*) AS period_jobs
    FROM dated_jobs
    GROUP BY market_period
),
period_skill_counts AS (
    SELECT
        j.market_period,
        s.skill,
        COUNT(DISTINCT j.job_key) AS skill_jobs
    FROM dated_jobs AS j
    JOIN bridge_job_skill AS b ON b.job_key = j.job_key
    JOIN dim_skill AS s ON s.skill_key = b.skill_key
    GROUP BY j.market_period, s.skill
)
SELECT
    p.market_period,
    p.skill,
    p.skill_jobs,
    t.period_jobs,
    ROUND(100.0 * p.skill_jobs / NULLIF(t.period_jobs, 0), 2)
        AS skill_share_pct
FROM period_skill_counts AS p
JOIN period_totals AS t ON t.market_period = p.market_period
ORDER BY p.skill, p.market_period;


/* ============================================================
   20. DATA-QUALITY CHECKS FOR REPORTING
   ============================================================ */

/* Placeholder-company names should not appear */
SELECT
    c.company_name,
    COUNT(*) AS job_count
FROM fact_jobs AS f
JOIN dim_company AS c
    ON f.company_key = c.company_key
WHERE LOWER(TRIM(c.company_name)) IN (
    'testhiring',
    'test',
    'demo',
    'sample company',
    'xyz company',
    'abc company',
    'dummy'
)
GROUP BY
    c.company_name
ORDER BY
    c.company_name;


/* Eligible salaries must contain valid positive ranges */
SELECT
    COUNT(*) AS invalid_salary_analysis_rows
FROM fact_jobs
WHERE salary_analysis_eligible
  AND (
      salary_min IS NULL
      OR salary_max IS NULL
      OR salary_midpoint IS NULL
      OR salary_min <= 0
      OR salary_max <= 0
      OR salary_max < salary_min
  );


/* Unique vacancy integrity */
SELECT
    COUNT(*) AS repeated_job_ids
FROM (
    SELECT
        job_id
    FROM fact_jobs
    GROUP BY
        job_id
    HAVING COUNT(*) > 1
) AS repeated_jobs;


/* Bridge uniqueness */
SELECT
    COUNT(*) AS repeated_job_skill_pairs
FROM (
    SELECT
        job_key,
        skill_key
    FROM bridge_job_skill
    GROUP BY
        job_key,
        skill_key
    HAVING COUNT(*) > 1
) AS repeated_pairs;



/* ============================================================
   21. SOURCE MIX AND SKILL EXTRACTION COVERAGE BY DATE PERIOD
   ============================================================ */

SELECT
    source_family,
    CASE
        WHEN NOT is_posting_date_observed THEN 'Proxy date / unknown period'
        WHEN is_recent_90d THEN 'Recent 90 Days'
        ELSE 'Earlier (Observed)'
    END AS market_period,
    COUNT(*) AS jobs,
    COUNT(*) FILTER (WHERE has_extracted_skill) AS skill_tagged_jobs,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE has_extracted_skill)
        / NULLIF(COUNT(*), 0), 2
    ) AS skill_extraction_coverage_pct
FROM fact_jobs
GROUP BY source_family, 2
ORDER BY source_family, market_period;


/* ============================================================
   22. SOURCE-STANDARDIZED SKILL SHARE (EXPLORATORY)
   ============================================================ */

WITH dated AS (
    SELECT
        job_key,
        source_family,
        CASE WHEN is_recent_90d THEN 'Recent 90 Days'
             ELSE 'Earlier (Observed)' END AS market_period
    FROM fact_jobs
    WHERE is_posting_date_observed
),
shared_sources AS (
    SELECT source_family
    FROM dated
    GROUP BY source_family
    HAVING COUNT(DISTINCT market_period) = 2
),
source_weights AS (
    SELECT
        d.source_family,
        COUNT(*)::NUMERIC / SUM(COUNT(*)) OVER () AS fixed_weight
    FROM dated AS d
    JOIN shared_sources AS ss USING (source_family)
    GROUP BY d.source_family
),
tracked_skills(skill) AS (
    VALUES ('SQL'), ('Excel'), ('Power BI'), ('Python'), ('Tableau')
),
source_period_totals AS (
    SELECT d.market_period, d.source_family, COUNT(*) AS source_jobs
    FROM dated AS d
    JOIN shared_sources AS ss USING (source_family)
    GROUP BY d.market_period, d.source_family
),
source_period_skills AS (
    SELECT
        d.market_period, d.source_family, s.skill,
        COUNT(DISTINCT d.job_key) AS skill_jobs
    FROM dated AS d
    JOIN shared_sources AS ss USING (source_family)
    JOIN bridge_job_skill AS b ON b.job_key = d.job_key
    JOIN dim_skill AS s ON s.skill_key = b.skill_key
    JOIN tracked_skills AS t ON t.skill = s.skill
    GROUP BY d.market_period, d.source_family, s.skill
),
source_rates AS (
    SELECT
        t.market_period,
        t.source_family,
        k.skill,
        t.source_jobs,
        COALESCE(s.skill_jobs, 0) AS skill_jobs,
        COALESCE(s.skill_jobs, 0)::NUMERIC / NULLIF(t.source_jobs, 0)
            AS skill_share
    FROM source_period_totals AS t
    CROSS JOIN tracked_skills AS k
    LEFT JOIN source_period_skills AS s
        ON s.market_period = t.market_period
       AND s.source_family = t.source_family
       AND s.skill = k.skill
)
SELECT
    r.market_period,
    r.skill,
    STRING_AGG(r.source_family, ', ' ORDER BY r.source_family)
        AS comparable_sources,
    SUM(r.source_jobs) AS sample_jobs,
    ROUND(100.0 * SUM(w.fixed_weight * r.skill_share), 2)
        AS standardized_skill_share_pct
FROM source_rates AS r
JOIN source_weights AS w ON w.source_family = r.source_family
GROUP BY r.market_period, r.skill
ORDER BY r.skill, r.market_period;


/* ============================================================
   23. ENTRY-LEVEL ROLE OPPORTUNITIES
   Experience bands 0-1 and 1-2 are explicit requirements; jobs
   with Not Specified must not be counted as entry-level openings.
   ============================================================ */

SELECT
    r.role_family,
    COUNT(*) AS all_jobs,
    COUNT(*) FILTER (WHERE f.experience_band IN ('0–1', '1–2'))
        AS jobs_with_0_to_2_year_band,
    COUNT(*) FILTER (WHERE f.experience_band = 'Not Specified')
        AS unspecified_experience_jobs,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE f.experience_band IN ('0–1', '1–2')
        ) / NULLIF(COUNT(*), 0), 2
    ) AS entry_band_share_of_all_jobs_pct
FROM fact_jobs AS f
JOIN dim_role AS r ON r.role_key = f.role_key
GROUP BY r.role_family
ORDER BY jobs_with_0_to_2_year_band DESC, r.role_family;


/* ============================================================
   24. METRO-AREA × ROLE DEMAND
   These are reporting groups only, not a change to raw locations.
   ============================================================ */

WITH metro_jobs AS (
    SELECT
        f.job_key,
        r.role_family,
        CASE
            WHEN l.city IN (
                'Delhi', 'New Delhi', 'Gurugram', 'Gurgaon',
                'Noida', 'Greater Noida', 'Faridabad', 'Ghaziabad'
            ) THEN 'Delhi NCR'
            WHEN l.city IN ('Hyderabad', 'Secunderabad')
                THEN 'Hyderabad Metro'
            WHEN l.city IN ('Bengaluru', 'Bangalore', 'Banglore', 'Bengalaru')
                THEN 'Bengaluru Metro'
            WHEN l.city IN ('Mumbai', 'Bombay', 'Thane', 'Navi Mumbai')
                THEN 'Mumbai Metro'
            ELSE l.city
        END AS market_area
    FROM fact_jobs AS f
    JOIN dim_location AS l ON l.location_key = f.location_key
    JOIN dim_role AS r ON r.role_key = f.role_key
    WHERE l.location_scope = 'Specific City'
      AND LOWER(TRIM(l.city)) NOT IN (
          'unknown', 'any', 'in', 'india', 'maharashtra',
          'telangana', 'karnataka', 'gujarat', 'haryana',
          'uttar pradesh', 'california', 'barcelona'
      )
),
market_totals AS (
    SELECT market_area, COUNT(*) AS all_area_jobs
    FROM metro_jobs
    GROUP BY market_area
),
role_counts AS (
    SELECT market_area, role_family, COUNT(*) AS role_jobs
    FROM metro_jobs
    GROUP BY market_area, role_family
)
SELECT
    c.market_area,
    c.role_family,
    c.role_jobs,
    t.all_area_jobs,
    ROUND(100.0 * c.role_jobs / NULLIF(t.all_area_jobs, 0), 2)
        AS area_role_share_pct
FROM role_counts AS c
JOIN market_totals AS t USING (market_area)
WHERE t.all_area_jobs >= 50
ORDER BY c.market_area, c.role_jobs DESC, c.role_family;


/* ============================================================
   25. METRO-AREA × SKILL DEMAND
   Denominator includes jobs with no extracted skills.
   ============================================================ */

WITH metro_jobs AS (
    SELECT
        f.job_key,
        CASE
            WHEN l.city IN ('Delhi', 'New Delhi', 'Gurugram', 'Gurgaon',
                'Noida', 'Greater Noida', 'Faridabad', 'Ghaziabad')
                THEN 'Delhi NCR'
            WHEN l.city IN ('Hyderabad', 'Secunderabad')
                THEN 'Hyderabad Metro'
            WHEN l.city IN ('Bengaluru', 'Bangalore', 'Banglore', 'Bengalaru')
                THEN 'Bengaluru Metro'
            WHEN l.city IN ('Mumbai', 'Bombay', 'Thane', 'Navi Mumbai')
                THEN 'Mumbai Metro'
            ELSE l.city
        END AS market_area
    FROM fact_jobs AS f
    JOIN dim_location AS l ON l.location_key = f.location_key
    WHERE l.location_scope = 'Specific City'
      AND LOWER(TRIM(l.city)) NOT IN (
          'unknown', 'any', 'in', 'india', 'maharashtra',
          'telangana', 'karnataka', 'gujarat', 'haryana',
          'uttar pradesh', 'california', 'barcelona'
      )
),
area_totals AS (
    SELECT market_area, COUNT(*) AS area_jobs
    FROM metro_jobs
    GROUP BY market_area
),
area_skill_counts AS (
    SELECT
        m.market_area, s.skill, COUNT(DISTINCT m.job_key) AS skill_jobs
    FROM metro_jobs AS m
    JOIN bridge_job_skill AS b ON b.job_key = m.job_key
    JOIN dim_skill AS s ON s.skill_key = b.skill_key
    GROUP BY m.market_area, s.skill
)
SELECT
    a.market_area,
    a.skill,
    a.skill_jobs,
    t.area_jobs,
    ROUND(100.0 * a.skill_jobs / NULLIF(t.area_jobs, 0), 2)
        AS skill_share_pct
FROM area_skill_counts AS a
JOIN area_totals AS t USING (market_area)
WHERE t.area_jobs >= 50
  AND a.skill IN ('SQL', 'Excel', 'Power BI', 'Python', 'Tableau')
ORDER BY a.market_area, skill_share_pct DESC, a.skill;


/* ============================================================
   26. POSSIBLE WITHIN-SOURCE DUPLICATES
   ============================================================ */

SELECT
    f.source_family,
    LOWER(TRIM(f.title)) AS normalized_title,
    LOWER(TRIM(c.company_name)) AS normalized_company,
    LOWER(TRIM(l.city)) AS normalized_city,
    f.date_key,
    COUNT(*) AS possible_duplicate_records
FROM fact_jobs AS f
JOIN dim_company AS c ON c.company_key = f.company_key
JOIN dim_location AS l ON l.location_key = f.location_key
GROUP BY 1, 2, 3, 4, 5
HAVING COUNT(*) > 1
ORDER BY possible_duplicate_records DESC, source_family
LIMIT 100;
