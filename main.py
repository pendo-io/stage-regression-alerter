"""
Stage Regression Alerter — Cloud Run Job entrypoint.

First run  (no rows in audit table): queries all regressions from WINDOW_START → today.
Daily runs (audit table has prior rows): queries only today.

State is stored in BQ (gtmaa_testing.stage_regression_alerts) so it survives
Cloud Run's ephemeral container lifecycle.
"""

import os
import sys
import logging
from datetime import date

from google.cloud import bigquery

from bq_query import fetch_regressions, WINDOW_START
from bq_logger import log_regressions, _TABLE
from slack_client import post_regressions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_CHANNEL"]


def _is_first_run(bq_project: str) -> bool:
    """Return True if the audit table has no previous runs."""
    client = bigquery.Client(project=bq_project)
    rows = list(client.query(
        f"SELECT 1 FROM `{_TABLE}` LIMIT 1"
    ).result())
    return len(rows) == 0


def main() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        log.error("Missing required environment variables: %s", missing)
        sys.exit(1)

    bq_project    = os.environ.get("BQ_PROJECT",  "pendo-reporting-ops")
    bq_dataset    = os.environ.get("BQ_DATASET",  "pendolytics_core_views")
    slack_token   = os.environ["SLACK_BOT_TOKEN"]
    slack_channel = os.environ["SLACK_CHANNEL"]

    today     = date.today()
    first_run = _is_first_run(bq_project)

    if first_run:
        start_date = date.fromisoformat(WINDOW_START)
        log.info("First run — querying all regressions from %s → %s", start_date, today)
    else:
        start_date = today
        log.info("Daily run — querying regressions for %s", today)

    regressions = fetch_regressions(bq_project, bq_dataset, start_date, today)
    log.info("Found %d regression(s)", len(regressions))

    post_regressions(
        slack_token,
        slack_channel,
        regressions,
        start_date=start_date,
        end_date=today,
        first_run=first_run,
    )

    log_regressions(bq_project, regressions, run_date=today, first_run=first_run)
    log.info("Done")


if __name__ == "__main__":
    main()
