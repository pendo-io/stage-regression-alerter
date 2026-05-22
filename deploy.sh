#!/usr/bin/env bash
# ============================================================
# deploy.sh — Build & deploy the Stage Regression Alerter
#
# Prerequisites:
#   1. gcloud authenticated:  gcloud auth login
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
# Use the existing default compute SA — no creation or IAM bindings needed
DEFAULT_SA="${PROJECT_ID//pendo-reporting-ops/265504543930}-compute@developer.gserviceaccount.com"
DEFAULT_SA="265504543930-compute@developer.gserviceaccount.com"
SECRET_NAME="stage-regression-slack-token"
SLACK_CHANNEL="#stage-regression-alerts"
SCHEDULE="0 9 * * 1-5"
SCHEDULE_TZ="America/New_York"
# ───────────────────────────────────────────────────────────

if [[ -z "${SLACK_BOT_TOKEN:-}" ]]; then
  echo "ERROR: SLACK_BOT_TOKEN environment variable is not set."
  echo "       Export it before running: export SLACK_BOT_TOKEN='xoxb-...'"
  exit 1
fi

echo "▶  Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

# ── 1. Artifact Registry repo (already exists, just verify) ─
echo "▶  Verifying Artifact Registry repo…"
gcloud artifacts repositories describe cloud-run-jobs \
  --location="${REGION}" --quiet

# ── 2. Build image locally and push to Artifact Registry ───
echo "▶  Authenticating Docker to Artifact Registry…"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "▶  Building Docker image…"
docker build --platform linux/amd64 -t "${IMAGE}" .

echo "▶  Pushing image to Artifact Registry…"
docker push "${IMAGE}"

# ── 3. Store Slack token in Secret Manager ─────────────────
echo "▶  Storing Slack bot token in Secret Manager…"
if gcloud secrets describe "${SECRET_NAME}" --quiet 2>/dev/null; then
  echo -n "${SLACK_BOT_TOKEN}" | \
    gcloud secrets versions add "${SECRET_NAME}" --data-file=- --quiet
else
  echo -n "${SLACK_BOT_TOKEN}" | \
    gcloud secrets create "${SECRET_NAME}" \
      --data-file=- \
      --replication-policy=automatic \
      --quiet
fi
echo "   Token stored as secret '${SECRET_NAME}'"

# ── 4. Create / update the Cloud Run Job ───────────────────
echo "▶  Deploying Cloud Run Job '${JOB_NAME}'…"
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --quiet 2>/dev/null; then
  VERB="update"
else
  VERB="create"
fi

gcloud run jobs "${VERB}" "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${DEFAULT_SA}" \
  --set-secrets="SLACK_BOT_TOKEN=${SECRET_NAME}:latest" \
  --set-env-vars="SLACK_CHANNEL=${SLACK_CHANNEL},BQ_PROJECT=${PROJECT_ID},BQ_DATASET=pendolytics_core_views" \
  --max-retries=2 \
  --task-timeout=300 \
  --memory=512Mi \
  --cpu=1 \
  --quiet

# ── 5. Cloud Scheduler trigger ─────────────────────────────
echo "▶  Setting up Cloud Scheduler job…"
if gcloud scheduler jobs describe "${JOB_NAME}-trigger" \
     --location="${REGION}" --quiet 2>/dev/null; then
  gcloud scheduler jobs update http "${JOB_NAME}-trigger" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${SCHEDULE_TZ}" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --message-body="{}" \
    --oauth-service-account-email="${DEFAULT_SA}" \
    --quiet
else
  gcloud scheduler jobs create http "${JOB_NAME}-trigger" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${SCHEDULE_TZ}" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --message-body="{}" \
    --oauth-service-account-email="${DEFAULT_SA}" \
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
