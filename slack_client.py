"""
Slack messaging layer.

Posts a Block Kit summary of stage regressions to the configured channel.
One message per run, with a row per regressed opportunity.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from bq_query import Regression

log = logging.getLogger(__name__)

# Slack caps Block Kit messages at 50 blocks. We reserve a few for the header,
# divider, and footer, leaving this many rows before we truncate.
_MAX_REGRESSION_ROWS = 40

# Salesforce Lightning base URL for Pendo
_SF_BASE_URL = "https://pendo.lightning.force.com/lightning/r/Opportunity"


def _fmt_money(val: float | None) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if abs(val) >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def _fmt_date(d: date) -> str:
    return d.strftime("%-m/%-d/%Y")


def _sf_link(opportunity_id: str, opportunity_name: str) -> str:
    url = f"{_SF_BASE_URL}/{opportunity_id}/view"
    return f"<{url}|{opportunity_name}>"


def _build_regression_row(r: Regression) -> dict[str, Any]:
    """Build a single Block Kit section for one regressed opportunity."""
    opp_link  = _sf_link(r.opportunity_id, r.opportunity_name)
    arr_str   = _fmt_money(r.arr)
    net_arr_str = _fmt_money(r.net_arr)
    close_str = _fmt_date(r.close_date) if r.close_date else "—"

    text = (
        f"*Date:* {_fmt_date(r.regression_date)}\n"
        f"*Opportunity:* {opp_link}\n"
        f"*Owner:* {r.owner_name}\n"
        f"*ARR:* {arr_str}  •  *Net ARR:* {net_arr_str}\n"
        f"*Close Date:* {close_str}\n"
        f"*Stage (yesterday):* {r.prev_stage_name}  →  *Stage (today):* {r.curr_stage_name}"
    )

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    }


def _build_blocks(
    regressions: list[Regression],
    start_date: date,
    end_date: date,
    first_run: bool,
) -> list[dict]:
    count = len(regressions)

    # ── No-regression case ───────────────────────────────────────────────────
    if count == 0:
        if first_run:
            msg = (
                f":white_check_mark: *Stage Regression Catchup — {_fmt_date(start_date)} → {_fmt_date(end_date)}*\n"
                "No opportunity stage regressions detected in this period. 🎉"
            )
        else:
            msg = (
                f":white_check_mark: *Stage Regression Check — {_fmt_date(end_date)}*\n"
                "No opportunity stage regressions detected today. 🎉"
            )
        return [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}]

    # ── Header ───────────────────────────────────────────────────────────────
    if first_run:
        header_text = (
            f":rotating_light: *Stage Regression Catchup — {_fmt_date(start_date)} → {_fmt_date(end_date)}*\n"
            f"*{count} regression event{'s' if count != 1 else ''}* detected since {_fmt_date(start_date)}."
        )
    else:
        header_text = (
            f":rotating_light: *Stage Regression Alert — {_fmt_date(end_date)}*\n"
            f"*{count} opportunit{'y' if count == 1 else 'ies'}* moved backward in stage since yesterday."
        )

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {"type": "divider"},
    ]

    # ── Regression rows (capped to avoid Slack's 50-block limit) ────────────
    visible   = regressions[:_MAX_REGRESSION_ROWS]
    truncated = count - len(visible)

    for r in visible:
        blocks.append(_build_regression_row(r))
        blocks.append({"type": "divider"})

    if truncated > 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_… and {truncated} more regression{'s' if truncated != 1 else ''} not shown._",
            },
        })

    # Remove trailing divider
    if blocks and blocks[-1]["type"] == "divider":
        blocks.pop()

    # ── Footer ───────────────────────────────────────────────────────────────
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                "Data source: `pendo-reporting-ops.pendolytics_core_views.opportunity_time_series` · "
                "Stage regression = stage_number decreased vs prior day snapshot"
            ),
        }],
    })

    return blocks


def post_regressions(
    slack_token: str,
    channel: str,
    regressions: list[Regression],
    start_date: date,
    end_date: date,
    first_run: bool,
) -> None:
    """Post a regression summary message to *channel*."""

    client = WebClient(token=slack_token)
    blocks = _build_blocks(regressions, start_date, end_date, first_run)

    count = len(regressions)
    if count == 0:
        fallback = f"Stage Regression Check {end_date}: No regressions detected."
    elif first_run:
        fallback = (
            f"Stage Regression Catchup {start_date} → {end_date}: "
            f"{count} regression event{'s' if count != 1 else ''} detected."
        )
    else:
        fallback = (
            f"Stage Regression Alert {end_date}: "
            f"{count} opportunit{'y' if count == 1 else 'ies'} moved backward in stage."
        )

    try:
        resp = client.chat_postMessage(
            channel=channel,
            text=fallback,
            blocks=blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
        log.info("Slack message posted: ts=%s channel=%s", resp["ts"], resp["channel"])
    except SlackApiError as exc:
        log.error("Slack API error: %s", exc.response["error"])
        raise
