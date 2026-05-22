# Stage Regression Alerter

A Cloud Run Job that queries BigQuery for Salesforce opportunities that moved **backward in stage** compared to the previous day's snapshot, then posts a summary to Slack.

**Runs:** Monday–Friday at 9 AM ET via Cloud Scheduler  
**Source:** `pendo-reporting-ops.pendolytics_core_views.opportunity_time_series`  
**Alerts to:** `#stage-regression-alerts`

---

## What counts as a regression?

A regression is any opportunity where today's `stage_number` is **less than** yesterday's `stage_number` — both must be numeric stages (0–5). Terminal/final states (Disqualified, Closed/Lost, Closed/Won, etc.) are excluded; moving into those is expected pipeline movement, not a regression.

| Stage number | Stage names |
|---|---|
| 0 | Stage 0 / Qualification |
| 1 | Stage 1 / Discovery |
| 2 | Stage 2 / Solution Evaluation |
| 3 | Stage 3 / Solution Acceptance |
| 4 | Stage 4 / Final Approval |
| 5 | Stage 5: Sales/Won |

---

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**
2. Name: `Stage Regression Alerter`, Workspace: Pendo
3. **OAuth & Permissions → Bot Token Scopes** — add:
   - `chat:write`
   - `chat:write.public` (lets the bot post without being invited to the channel)
4. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`)
5. Create the `#stage-regression-alerts` channel in Slack

### 2. Deploy to GCP

```bash
cd stage-regression-alerts

# Authenticate (one-time if not already done)
gcloud auth login
gcloud auth application-default login

# Deploy everything
export SLACK_BOT_TOKEN="xoxb-your-token-here"
./deploy.sh
```

The script handles:
- Enabling required GCP APIs
- Creating an Artifact Registry repo and building/pushing the Docker image via Cloud Build
- Creating a dedicated service account with minimum IAM roles
- Storing the Slack token in Secret Manager
- Creating/updating the Cloud Run Job
- Setting up Cloud Scheduler to trigger it Mon–Fri at 9 AM ET

### 3. Test manually

```bash
gcloud run jobs execute stage-regression-alerter \
  --region=us-east1 \
  --wait
```

Check logs:

```bash
gcloud run jobs executions list \
  --job=stage-regression-alerter \
  --region=us-east1

# Tail logs of the latest execution
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="stage-regression-alerter"' \
  --limit=50 \
  --format='value(textPayload)' \
  --project=pendo-reporting-ops
```

---

## Project structure

```
stage-regression-alerts/
├── main.py          # Entrypoint — orchestrates BQ query + Slack post
├── bq_query.py      # BigQuery logic; returns list[Regression] dataclasses
├── slack_client.py  # Slack Block Kit formatter + WebClient post
├── requirements.txt
├── Dockerfile       # python:3.12-slim, no server — exits after run
├── deploy.sh        # One-shot GCP deploy script
└── README.md
```

---

## Changing the schedule

Edit `SCHEDULE` in `deploy.sh` (standard cron syntax, UTC by default — `SCHEDULE_TZ` overrides):

```bash
SCHEDULE="0 9 * * 1-5"      # 9 AM Mon–Fri (current)
SCHEDULE="0 8 * * 1-5"      # 8 AM Mon–Fri
SCHEDULE="0 13 * * 1-5"     # 9 AM ET = 1 PM UTC (if you want UTC)
```

Re-run `./deploy.sh` to apply changes.

---

## Updating the Slack token

```bash
echo -n "xoxb-new-token" | \
  gcloud secrets versions add stage-regression-slack-token \
    --data-file=- \
    --project=pendo-reporting-ops
```

No redeploy needed — the job always fetches `latest`.
