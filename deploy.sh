#!/usr/bin/env bash
# ============================================================
# deploy.sh — Build & deploy the Stage Regression Alerter
#
# Prerequisites:
#   1. gcloud authenticated:  gcloud auth login && gcloud auth application-default login
#   2. Docker running locally
#   3. SLACK_BOT_TOKEN env var set with your bot token
#
# Usage:
#   SLACK_BOT_TOKEN="xoxb-..." ./deploy.sh
# ============================================================

set -euo pipefail

# ── Config ─────────────────────────────────────────────────
PROJECT_ID="pendo-reporting-ops"
REGION="us-east1"
JOB_NAME="stage-regression-alerter"
IMAGE="us-east1-docker.pkg.dev/${PROJECT_ID}/cloud-run-jobs/${JOB_NAME}"
SA_NAME="stage-regression-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="stage-regression-slack-token"
SLACK_CHANNEL="#stage-regression-alerts"
SCHEDULE="0 9 * * 1-5"        # 9 AM ET, Mon–Fri  (Cloud Scheduler uses UTC; adjust if needed)
SCHEDULE_TZ="America/New_York"
# ───────────────────────────────────────────────────────────

if [[ -z "${SLACK_BOT_TOKEN:-}" ]]; then
  echo "ERROR: SLACK_BOT_TOKEN environment variable is not set."
  echo "       Export it before running: export SLACK_BOT_TOKEN='xoxb-...'"
  exit 1
fi

echo "▶  Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

# ── 1. Enable required APIs ─────────────────────────────────
echo "▶  Enabling required APIs…"
if ! gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  --quiet 2>&1; then
  echo "⚠️  Could not enable APIs (insufficient permissions)."
  echo "   Ask a GCP project owner to enable these on ${PROJECT_ID}:"
  echo "     run.googleapis.com, cloudscheduler.googleapis.com,"
  echo "     secretmanager.googleapis.com, artifactregistry.googleapis.com"
  echo "   Continuing — will fail below if APIs aren't already on…"
fi

# ── 2. Artifact Registry repo ──────────────────────────────
echo "▶  Ensuring Artifact Registry repo exists…"
gcloud artifacts repositories describe cloud-run-jobs \
  --location="${REGION}" --quiet 2>/dev/null || \
gcloud artifacts repositories create cloud-run-jobs \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Cloud Run job images" \
  --quiet

# ── 3. Build & push image ──────────────────────────────────
echo "▶  Building and pushing Docker image…"
gcloud builds submit . \
  --tag="${IMAGE}" \
  --region="${REGION}" \
  --quiet

# ── 4. Service account ─────────────────────────────────────
echo "▶  Ensuring service account exists…"
gcloud iam service-accounts describe "${SA_EMAIL}" --quiet 2>/dev/null || \
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Stage Regression Alerter" \
  --quiet

# Grant BigQuery read access
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataViewer" \
  --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --quiet

# Grant Secret Manager access
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet

# ── 5. Store Slack token in Secret Manager ─────────────────
echo "▶  Storing Slack bot token in Secret Manager…"
if gcloud secrets describe "${SECRET_NAME}" --quiet 2>/dev/null; then
  # Secret exists — add a new version
  echo -n "${SLACK_BOT_TOKEN}" | \
    gcloud secrets versions add "${SECRET_NAME}" --data-file=- --quiet
else
  # Create the secret
  echo -n "${SLACK_BOT_TOKEN}" | \
    gcloud secrets create "${SECRET_NAME}" \
      --data-file=- \
      --replication-policy=automatic \
      --quiet
fi
echo "   Token stored as secret '${SECRET_NAME}'"

# ── 6. Create / update the Cloud Run Job ───────────────────
echo "▶  Deploying Cloud Run Job '${JOB_NAME}'…"
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --quiet 2>/dev/null; then
  VERB="update"
else
  VERB="create"
fi

gcloud run jobs "${VERB}" "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --set-secrets="SLACK_BOT_TOKEN=${SECRET_NAME}:latest" \
  --set-env-vars="SLACK_CHANNEL=${SLACK_CHANNEL},BQ_PROJECT=${PROJECT_ID},BQ_DATASET=pendolytics_core_views" \
  --max-retries=2 \
  --task-timeout=300 \
  --memory=512Mi \
  --cpu=1 \
  --quiet

# ── 7. Cloud Scheduler trigger ─────────────────────────────
echo "▶  Setting up Cloud Scheduler job…"
SCHEDULER_SA="${SA_EMAIL}"

# Grant the SA permission to invoke the Cloud Run Job
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --quiet

JOB_RESOURCE="projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}"

if gcloud scheduler jobs describe "${JOB_NAME}-trigger" \
     --location="${REGION}" --quiet 2>/dev/null; then
  gcloud scheduler jobs update http "${JOB_NAME}-trigger" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${SCHEDULE_TZ}" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --message-body="{}" \
    --oauth-service-account-email="${SCHEDULER_SA}" \
    --quiet
else
  gcloud scheduler jobs create http "${JOB_NAME}-trigger" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${SCHEDULE_TZ}" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --message-body="{}" \
    --oauth-service-account-email="${SCHEDULER_SA}" \
    --quiet
fi

# ── Done ───────────────────────────────────────────────────
echo ""
echo "✅  Deployment complete!"
echo ""
echo "   Cloud Run Job : ${JOB_NAME} (${REGION})"
echo "   Schedule      : ${SCHEDULE} ${SCHEDULE_TZ} (Mon–Fri)"
echo "   Slack channel : ${SLACK_CHANNEL}"
echo ""
echo "   Test it now:"
echo "   gcloud run jobs execute ${JOB_NAME} --region=${REGION} --wait"
