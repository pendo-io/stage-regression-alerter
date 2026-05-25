"""
Stage Regression Alerter — Cloud Run Job entrypoint.

Runs daily. Queries opportunity_time_series for today's date only,
detecting any opportunities whose stage_number dropped vs yesterday.
"""

import os
import sys
import logging
from datetime import date

from bq_query import fetch_regressions
from bq_logger import log_regressions
from slack_client import post_regressions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_CHANNEL"]


def main() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        log.error("Missing required environment variables: %s", missing)
        sys.exit(1)

    bq_project    = os.environ.get("BQ_PROJECT",  "pendo-reporting-ops")
    bq_dataset    = os.environ.get("BQ_DATASET",  "pendolytics_core_views")
    slack_token   = os.environ["SLACK_BOT_TOKEN"]
    slack_channel = os.environ["SLACK_CHANNEL"]

    today = date.today()
    log.info("Running regression check for %s", today)

    regressions = fetch_regressions(bq_project, bq_dataset, start_date=today, end_date=today)
    log.info("Found %d regression(s)", len(regressions))

    post_regressions(
        slack_token,
        slack_channel,
        regressions,
        start_date=today,
        end_date=today,
        first_run=False,
    )

    log_regressions(bq_project, regressions, run_date=today, first_run=False)
    log.info("Done")


if __name__ == "__main__":
    main()
