"""
BigQuery query logic for detecting opportunity stage regressions.

A regression is defined as: today's stage_number < yesterday's stage_number,
where both stages have a numeric stage_number (i.e. we ignore terminal states
like Disqualified, Closed/Lost, In-Contract, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from google.cloud import bigquery

log = logging.getLogger(__name__)


@dataclass
class Regression:
    opportunity_id: str
    opportunity_name: str
    account_name: str
    owner_name: str
    prev_stage_name: str
    prev_stage_number: int
    curr_stage_name: str
    curr_stage_number: int
    arr: Optional[float]
    net_arr: Optional[float]
    blended_team: Optional[str]
    blended_region: Optional[str]
    close_date: Optional[date]
    regression_date: date          # the snapshot date the regression was detected on


# Only flag regressions on opportunities whose close date falls in this window.
# The same window also gates which time-series rows we scan.
WINDOW_START = "2026-05-01"
WINDOW_END   = "2026-07-31"

# Query accepts a date range. For daily runs start_date == end_date == today.
# For the first-run catchup, start_date = WINDOW_START and end_date = today.
_REGRESSION_QUERY = """
WITH stage_map AS (
  -- Build a canonical stage_name → stage_number lookup.
  -- Some stage names share a stage_number (e.g. "Stage 0" and "Qualification");
  -- we take the MIN to keep it deterministic.
  SELECT stage_name, MIN(stage_number) AS stage_number
  FROM `{project}.{dataset}.opportunity_time_series`
  WHERE stage_number IS NOT NULL
  GROUP BY stage_name
),
candidates AS (
  SELECT
    ots.date                         AS regression_date,
    ots.opportunity_id,
    ots.opportunity_name,
    ots.account_name,
    ots.owner_name,
    ots.previous_day_stage_name,
    prev_map.stage_number            AS prev_stage_number,
    ots.stage_name                   AS curr_stage_name,
    ots.stage_number                 AS curr_stage_number,
    ots.arr,
    ots.net_arr,
    ots.blended_team,
    ots.blended_region,
    ots.close_date
  FROM `{project}.{dataset}.opportunity_time_series` ots
  LEFT JOIN stage_map prev_map
         ON prev_map.stage_name = ots.previous_day_stage_name
  WHERE ots.date BETWEEN @start_date AND @end_date
    -- Only scan rows within the close-date window (partition pruning + relevance)
    AND ots.date      BETWEEN DATE('{window_start}') AND DATE('{window_end}')
    AND ots.close_date BETWEEN DATE('{window_start}') AND DATE('{window_end}')
    AND ots.previous_day_stage_name IS NOT NULL
    AND ots.stage_name != ots.previous_day_stage_name
)
SELECT *
FROM candidates
WHERE
  curr_stage_number IS NOT NULL
  AND prev_stage_number IS NOT NULL
  AND curr_stage_number < prev_stage_number
ORDER BY regression_date DESC, arr DESC NULLS LAST, opportunity_name
"""


def fetch_regressions(
    bq_project: str,
    bq_dataset: str,
    start_date: date,
    end_date: date,
) -> list[Regression]:
    """Return all opportunity stage regressions between *start_date* and *end_date* inclusive."""

    client = bigquery.Client(project=bq_project)

    sql = _REGRESSION_QUERY.format(
        project=bq_project,
        dataset=bq_dataset,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date.isoformat()),
            bigquery.ScalarQueryParameter("end_date",   "DATE", end_date.isoformat()),
        ]
    )

    log.info("Running regression query for %s → %s", start_date, end_date)
    rows = list(client.query(sql, job_config=job_config).result())
    log.info("Query returned %d row(s)", len(rows))

    return [
        Regression(
            opportunity_id=row.opportunity_id,
            opportunity_name=row.opportunity_name,
            account_name=row.account_name,
            owner_name=row.owner_name,
            prev_stage_name=row.previous_day_stage_name,
            prev_stage_number=int(row.prev_stage_number),
            curr_stage_name=row.curr_stage_name,
            curr_stage_number=int(row.curr_stage_number),
            arr=float(row.arr) if row.arr is not None else None,
            net_arr=float(row.net_arr) if row.net_arr is not None else None,
            blended_team=row.blended_team,
            blended_region=row.blended_region,
            close_date=row.close_date,
            regression_date=row.regression_date,
        )
        for row in rows
    ]
