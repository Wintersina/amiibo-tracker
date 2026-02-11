#!/bin/bash
# Idempotent script to create or update Cloud Scheduler job for Nintendo amiibo scraper
# Safe to run multiple times - will update if exists, create if doesn't exist

set -e  # Exit on error

# Configuration
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-amiibo-tracker}"
JOB_NAME="nintendo-amiibo-scraper"
SCHEDULE="${SCHEDULE:-0 2,14 * * *}"  # Twice daily at 2 AM and 2 PM (can be overridden)
TIMEZONE="${TIMEZONE:-America/Los_Angeles}"  # Can be overridden

# Validate required variables
if [ -z "$PROJECT_ID" ]; then
  echo "❌ Error: PROJECT_ID environment variable is required"
  exit 1
fi

# Get the Cloud Run service URL
echo "🔍 Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$SERVICE_URL" ]; then
  echo "❌ Error: Could not find Cloud Run service '$SERVICE_NAME' in region '$REGION'"
  exit 1
fi

SCRAPER_URL="$SERVICE_URL/api/scrape-nintendo/"
echo "✅ Service URL: $SERVICE_URL"
echo "📡 Scraper endpoint: $SCRAPER_URL"

# Get the default compute service account
SERVICE_ACCOUNT=$(gcloud iam service-accounts list \
  --project "$PROJECT_ID" \
  --filter="email:$PROJECT_ID-compute@developer.gserviceaccount.com" \
  --format="value(email)" 2>/dev/null || echo "")

if [ -z "$SERVICE_ACCOUNT" ]; then
  # Fallback to project number based service account
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
  SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
fi

echo "🔐 Using service account: $SERVICE_ACCOUNT"

# Ensure Cloud Scheduler API is enabled
echo "🔧 Ensuring Cloud Scheduler API is enabled..."
gcloud services enable cloudscheduler.googleapis.com --project "$PROJECT_ID" 2>/dev/null || true

# Check if job exists
echo "🔍 Checking if scheduler job exists..."
JOB_EXISTS=$(gcloud scheduler jobs describe "$JOB_NAME" \
  --location "$REGION" \
  --project "$PROJECT_ID" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -n "$JOB_EXISTS" ]; then
  echo "♻️  Updating existing scheduler job..."
  gcloud scheduler jobs update http "$JOB_NAME" \
    --location "$REGION" \
    --project "$PROJECT_ID" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIMEZONE" \
    --uri "$SCRAPER_URL" \
    --http-method POST \
    --oidc-service-account-email "$SERVICE_ACCOUNT" \
    --description "Auto-scrape Nintendo amiibo lineup twice daily" \
    --quiet

  echo "✅ Scheduler job updated successfully!"
else
  echo "➕ Creating new scheduler job..."

  # Ensure the App Engine app exists (required for Cloud Scheduler in some regions)
  APP_ENGINE_REGION=$(gcloud app describe --project "$PROJECT_ID" --format="value(locationId)" 2>/dev/null || echo "")
  if [ -z "$APP_ENGINE_REGION" ]; then
    echo "ℹ️  Cloud Scheduler requires App Engine app (no compute resources)..."
    echo "   Creating App Engine app in region: $REGION"
    gcloud app create --region="$REGION" --project "$PROJECT_ID" 2>/dev/null || true
  fi

  gcloud scheduler jobs create http "$JOB_NAME" \
    --location "$REGION" \
    --project "$PROJECT_ID" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIMEZONE" \
    --uri "$SCRAPER_URL" \
    --http-method POST \
    --oidc-service-account-email "$SERVICE_ACCOUNT" \
    --description "Auto-scrape Nintendo amiibo lineup twice daily" \
    --quiet

  echo "✅ Scheduler job created successfully!"
fi

# Verify the job
echo ""
echo "📋 Scheduler Job Details:"
gcloud scheduler jobs describe "$JOB_NAME" \
  --location "$REGION" \
  --project "$PROJECT_ID" \
  --format="table(name, schedule, state, httpTarget.uri)"

echo ""
echo "✨ Setup complete! The scraper will run twice daily (2 AM and 2 PM) automatically."
echo ""
echo "🧪 To test the job manually, run:"
echo "   gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo ""
echo "📊 To view job history and logs:"
echo "   gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo ""
