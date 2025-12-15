#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-amiibo-tracker}"
REGION="${2:-${GCP_REGION:-us-central1}}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required to verify Cloud Run deployment." >&2
  exit 1
fi

if ! gcloud config get-value project >/dev/null 2>&1; then
  echo "Set an active gcloud project before running this script." >&2
  exit 1
fi

echo "Fetching Cloud Run URL for service '${SERVICE_NAME}' in region '${REGION}'..."
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(status.url)" 2>/dev/null || true)

if [[ -z "${SERVICE_URL}" ]]; then
  echo "Cloud Run service not found. Ensure it is deployed and that you have permission to describe it." >&2
  exit 1
fi

echo "Service URL: ${SERVICE_URL}"

echo "Performing HTTP health check..."
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to perform the health check." >&2
  exit 1
fi

HTTP_STATUS=$(curl -k -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/")

echo "Received status code: ${HTTP_STATUS}"

if [[ "${HTTP_STATUS}" != "200" && "${HTTP_STATUS}" != "302" ]]; then
  echo "Unexpected status code from service. Investigate Cloud Run logs for details." >&2
  exit 1
fi

echo "Cloud Run deployment looks healthy."
