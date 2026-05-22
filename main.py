"""
Stage Regression Alerter — Cloud Run Job / local entrypoint.

First run  (no state file): queries all regressions from WINDOW_START → today.
Daily runs (state file exists): queries only today.

State file: ~/.stage-regression-alerter/last_run
"""

import os
import sys
import logging
from datetime import date, datetime
from pathlib import Path

from bq_query import fetch_regressions, WINDOW_START
from bq_logger import log_regressions
from slack_client import post_regressions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

REQUIRED_ENV  = ["SLACK_BOT_TOKEN", "SLACK_CHANNEL"]
STATE_FILE    = Path.home() / ".stage-regression-alerter" / "last_run"


def _read_state() -> date | None:
    """Return the date of the last successful run, or None if this is the first run."""
    if not STATE_FILE.exists():
        return None
    try:
        return date.fromisoformat(STATE_FILE.read_text().strip())
    except ValueError:
        return None


def _write_state(run_date: date) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(run_date.isoformat())
    log.info("State file updated: %s", STATE_FILE)


def main() -> None:
    # Validate environment
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        log.error("Missing required environment variables: %s", missing)
        sys.exit(1)

    bq_project  = os.environ.get("BQ_PROJECT",  "pendo-reporting-ops")
    bq_dataset  = os.environ.get("BQ_DATASET",  "pendolytics_core_views")
    slack_token = os.environ["SLACK_BOT_TOKEN"]
    slack_channel = os.environ["SLACK_CHANNEL"]

    today      = date.today()
    last_run   = _read_state()
    first_run  = last_run is None

    if first_run:
        start_date = date.fromisoformat(WINDOW_START)
        log.info("First run detected — querying all regressions from %s → %s", start_date, today)
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

    _write_state(today)
    log.info("Done")


if __name__ == "__main__":
    main()
