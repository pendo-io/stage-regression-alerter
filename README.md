# Stage Regression Alerter

A Cloud Run Job that queries BigQuery for Salesforce opportunities that moved **backward in stage** compared to the previous day's snapshot, then posts a summary to Slack.

**Runs:** Monday–Friday at 9 AM ET via Cloud Scheduler  
**Source:** `pendo-reporting-ops.pendolytics_core_views.opportunity_time_series`  
**Alerts to:** `#stage-regression-alerts`  
**Audit log:** `pendo-reporting-ops.gtmaa_testing.stage_regression_alerts`

---

## What counts as a regression?

A regression is any opportunity where today's `stage_number` is **less than** yesterday's `stage_number` — both must be numeric stages (0–5). Terminal states (Disqualified, Closed/Lost, Closed/Won, etc.) are excluded.

| Stage number | Stage names |
|---|---|
| 0 | Stage 0 / Qualification |
| 1 | Stage 1 / Discovery |
| 2 | Stage 2 / Solution Evaluation |
| 3 | Stage 3 / Solution Acceptance |
| 4 | Stage 4 / Final Approval |
| 5 | Stage 5: Sales/Won |

Only opportunities with a close date between **2026-05-01 and 2026-07-31** are included.

---

## GCP Permissions

### What this project uses

| GCP Resource | Purpose |
|---|---|
| **Artifact Registry** | Stores the Docker container image |
| **Cloud Run Job** | Runs the Python script on schedule |
| **Cloud Scheduler** | Triggers the Job Mon–Fri at 9 AM ET |
| **BigQuery** | Reads `opportunity_time_series`; writes to audit table |

### Permissions required to deploy

The person running `deploy.sh` needs these roles on `pendo-reporting-ops`:

| Role | Why it's needed |
|---|---|
| `roles/artifactregistry.admin` | Create repo, push Docker image |
| `roles/iam.serviceAccountUser` | Allow Cloud Run to run as a service account |
| `roles/run.admin` | Create and update Cloud Run Jobs |
| `roles/cloudscheduler.admin` | Create the scheduled trigger |
| `roles/serviceusage.serviceUsageConsumer` | Use GCP APIs (Cloud Build, etc.) |
| `roles/storage.admin` | Cloud Build staging bucket access |

Ask your GCP project owner to grant these in one command:

```bash
for ROLE in \
  roles/artifactregistry.admin \
  roles/iam.serviceAccountUser \
  roles/run.admin \
  roles/cloudscheduler.admin \
  roles/serviceusage.serviceUsageConsumer \
  roles/storage.admin; do
  gcloud projects add-iam-policy-binding pendo-reporting-ops \
    --member="user:YOUR_EMAIL@pendo.io" \
    --role="$ROLE"
done
```

### Service account

This project uses the **default Compute Engine service account**:
```
265504543930-compute@developer.gserviceaccount.com
```

This is the identity the Cloud Run Job runs as at runtime. It needs:

| Role | Why it's needed |
|---|---|
| `roles/bigquery.dataViewer` | Read `opportunity_time_series` |
| `roles/bigquery.jobUser` | Execute BQ queries |
| `roles/bigquery.dataEditor` | Write results to the audit table |

Ask your GCP project owner to grant these:

```bash
for ROLE in \
  roles/bigquery.dataViewer \
  roles/bigquery.jobUser \
  roles/bigquery.dataEditor; do
  gcloud projects add-iam-policy-binding pendo-reporting-ops \
    --member="serviceAccount:265504543930-compute@developer.gserviceaccount.com" \
    --role="$ROLE"
done
```

### Checking your own permissions

To verify which permissions you currently have before deploying:

```bash
pip3 install -q google-cloud-resource-manager && python3 - <<'EOF'
from google.cloud import resourcemanager_v3

client = resourcemanager_v3.ProjectsClient()
needed = [
    "artifactregistry.repositories.create",
    "cloudbuild.builds.create",
    "iam.serviceAccounts.actAs",
    "run.jobs.create",
    "cloudscheduler.jobs.create",
    "serviceusage.services.use",
    "storage.buckets.create",
]
resp = client.test_iam_permissions(
    request={"resource": "projects/pendo-reporting-ops", "permissions": needed}
)
have = set(resp.permissions)
print("✅ Have:", sorted(have))
print("❌ Missing:", [p for p in needed if p not in have])
EOF
```

---

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From a manifest**
2. Paste this manifest:

```yaml
display_information:
  name: Stage Regression Alerter
  description: Alerts when a Salesforce opportunity moves backward in stage
  background_color: "#c0392b"
features:
  bot_user:
    display_name: Stage Regression Alerter
    always_online: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - chat:write.public
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

3. **OAuth & Permissions → Install to Workspace → Allow**
4. Copy the **Bot User OAuth Token** (`xoxb-...`)
5. Create the `#stage-regression-alerts` channel in Slack

### 2. Deploy from Cloud Shell

Open [Cloud Shell](https://console.cloud.google.com) (the `>_` icon in GCP console) — it has Docker and gcloud pre-installed, no local setup needed.

```bash
git clone https://github.com/pendo-io/stage-regression-alerter.git
cd stage-regression-alerter
export SLACK_BOT_TOKEN="xoxb-your-token-here"
./deploy.sh
```

### 3. Test manually

In Cloud Shell:

```bash
gcloud run jobs execute stage-regression-alerter \
  --region=us-east1 \
  --wait
```

View execution history and logs:
```
https://console.cloud.google.com/run/jobs/details/us-east1/stage-regression-alerter?project=pendo-reporting-ops
```

### 4. View the schedule

```
https://console.cloud.google.com/cloudscheduler?project=pendo-reporting-ops
```

Job name: `stage-regression-alerter-trigger` — fires Mon–Fri at 9 AM ET.

---

## Project structure

```
stage-regression-alerter/
├── main.py          # Entrypoint — queries BQ, posts to Slack, logs to BQ
├── bq_query.py      # BigQuery regression detection query
├── bq_logger.py     # Appends results to gtmaa_testing.stage_regression_alerts
├── slack_client.py  # Slack Block Kit formatter + WebClient post
├── requirements.txt
├── Dockerfile       # python:3.12-slim, exits after run (no web server)
├── deploy.sh        # Deploy from Cloud Shell
└── README.md
```

---

## Redeploying after code changes

Always deploy from Cloud Shell to pick up the latest code:

```bash
cd ~/stage-regression-alerter
git fetch origin && git reset --hard origin/main
export SLACK_BOT_TOKEN="xoxb-your-token-here"
./deploy.sh
```

---

## Changing the schedule

Edit `SCHEDULE` in `deploy.sh`:

```bash
SCHEDULE="0 9 * * 1-5"      # 9 AM Mon–Fri ET (current)
SCHEDULE="0 8 * * 1-5"      # 8 AM Mon–Fri ET
```

Re-run `./deploy.sh` to apply.

---

## Updating the Slack token

Rotate the token in the Slack app (OAuth & Permissions → Revoke → Reinstall), then redeploy:

```bash
cd ~/stage-regression-alerter
export SLACK_BOT_TOKEN="xoxb-new-token"
./deploy.sh
```

---

## Audit log queries

```sql
-- All regressions ever detected
SELECT * FROM `pendo-reporting-ops.gtmaa_testing.stage_regression_alerts`
WHERE opportunity_id IS NOT NULL
ORDER BY logged_at DESC;

-- Regression count by rep
SELECT owner_name, COUNT(*) AS regressions
FROM `pendo-reporting-ops.gtmaa_testing.stage_regression_alerts`
WHERE opportunity_id IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;

-- All runs (including clean days with no regressions)
SELECT run_date, COUNT(*) AS rows_logged
FROM `pendo-reporting-ops.gtmaa_testing.stage_regression_alerts`
GROUP BY 1 ORDER BY 1 DESC;
```
