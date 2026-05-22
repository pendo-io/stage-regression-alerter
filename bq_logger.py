"""
Logs regression results to BigQuery for historical tracking.

Table: pendo-reporting-ops.gtmaa_testing.stage_regression_alerts
Each run appends one row per regression (plus one sentinel row when there
are zero regressions, so every execution is auditable).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from google.cloud import bigquery

from bq_query import Regression

log = logging.getLogger(__name__)

_TABLE = "pendo-reporting-ops.gtmaa_testing.stage_regression_alerts"


def _to_row(
    r: Regression,
    run_id: str,
    run_date: date,
    first_run: bool,
    logged_at: datetime,
) -> dict:
    return {
        "run_id":            run_id,
        "run_date":          run_date.isoformat(),
        "first_run":         first_run,
        "logged_at":         logged_at.isoformat(),
        "regression_date":   r.regression_date.isoformat(),
        "opportunity_id":    r.opportunity_id,
        "opportunity_name":  r.opportunity_name,
        "account_name":      r.account_name,
        "owner_name":        r.owner_name,
        "prev_stage_name":   r.prev_stage_name,
        "prev_stage_number": r.prev_stage_number,
        "curr_stage_name":   r.curr_stage_name,
        "curr_stage_number": r.curr_stage_number,
        "arr":               r.arr,
        "net_arr":           r.net_arr,
        "blended_team":      r.blended_team,
        "blended_region":    r.blended_region,
        "close_date":        r.close_date.isoformat() if r.close_date else None,
    }


def log_regressions(
    bq_project: str,
    regressions: list[Regression],
    run_date: date,
    first_run: bool,
) -> None:
    """Append all regression rows for this run to the audit table.

    If there are no regressions we still insert one row with nulled-out
    opportunity fields so every execution appears in the log.
    """
    client    = bigquery.Client(project=bq_project)
    run_id    = str(uuid.uuid4())
    logged_at = datetime.now(timezone.utc)

    if regressions:
        rows = [_to_row(r, run_id, run_date, first_run, logged_at) for r in regressions]
    else:
        # Sentinel row — marks a clean run in the audit trail
        rows = [{
            "run_id":            run_id,
            "run_date":          run_date.isoformat(),
            "first_run":         first_run,
            "logged_at":         logged_at.isoformat(),
            "regression_date":   None,
            "opportunity_id":    None,
            "opportunity_name":  None,
            "account_name":      None,
            "owner_name":        None,
            "prev_stage_name":   None,
            "prev_stage_number": None,
            "curr_stage_name":   None,
            "curr_stage_number": None,
            "arr":               None,
            "net_arr":           None,
            "blended_team":      None,
            "blended_region":    None,
            "close_date":        None,
        }]

    errors = client.insert_rows_json(_TABLE, rows)
    if errors:
        log.error("BQ insert errors: %s", errors)
        raise RuntimeError(f"Failed to log {len(errors)} row(s) to BigQuery")

    log.info(
        "Logged %d row(s) to %s (run_id=%s)",
        len(rows), _TABLE, run_id,
    )
