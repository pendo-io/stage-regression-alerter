#!/usr/bin/env bash
# ============================================================
# deploy.sh — Build & deploy the Stage Regression Alerter
#
# Prerequisites:
#   1. gcloud authenticated (Cloud Shell is pre-authenticated)
#   2. SLACK_BOT_TOKEN env var set with your Slack bot token
#
# Usage (from Cloud Shell):
#   git clone https://github.com/pendo-io/stage-regression-alerter
#   cd stage-regression-alerter
#   export SLACK_BOT_TOKEN="xoxb-..."
#   ./deploy.sh
# ============================================================

set -euo pipefail

# ── Config ─────────────────────────────────────────────────
PROJECT_ID="pendo-reporting-ops"
REGION="us-east1"
JOB_NAME="stage-regression-alerter"
IMAGE="us-east1-docker.pkg.dev/${PROJECT_ID}/cloud-run-jobs/${JOB_NAME}"
DEFAULT_SA="265504543930-compute@developer.gserviceaccount.com"
SLACK_CHANNEL="#stage-regression-alerts"
SCHEDULE="0 9 * * 1-5"        # 9 AM ET, Mon–Fri
SCHEDULE_TZ="America/New_York"
# ───────────────────────────────────────────────────────────

if [[ -z "${SLACK_BOT_TOKEN:-}" ]]; then
  echo "ERROR: SLACK_BOT_TOKEN is not set."
  echo "       Export it before running: export SLACK_BOT_TOKEN='xoxb-...'"
  exit 1
fi

echo "▶  Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

# ── 1. Artifact Registry repo ──────────────────────────────
echo "▶  Verifying Artifact Registry repo…"
gcloud artifacts repositories describe cloud-run-jobs \
  --location="${REGION}" --quiet

# ── 2. Build & push image ──────────────────────────────────
echo "▶  Authenticating Docker to Artifact Registry…"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "▶  Building Docker image…"
docker build --platform linux/amd64 -t "${IMAGE}" .

echo "▶  Pushing image to Artifact Registry…"
docker push "${IMAGE}"

# ── 3. Create / update the Cloud Run Job ───────────────────
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
  --set-env-vars="SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN},SLACK_CHANNEL=${SLACK_CHANNEL},BQ_PROJECT=${PROJECT_ID},BQ_DATASET=pendolytics_core_views" \
  --max-retries=2 \
  --task-timeout=300 \
  --memory=512Mi \
  --cpu=1 \
  --quiet

# ── 4. Cloud Scheduler trigger ─────────────────────────────
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
