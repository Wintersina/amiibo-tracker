#!/bin/bash
# Setup Google Cloud Scheduler to run scraper automatically

# Configuration
PROJECT_ID="your-project-id"
REGION="us-central1"
SERVICE_URL="https://your-app.run.app/api/scrape-nintendo"
SCHEDULE="0 */6 * * *"  # Every 6 hours

# Create Cloud Scheduler job
gcloud scheduler jobs create http nintendo-amiibo-scraper \
  --location=$REGION \
  --schedule="$SCHEDULE" \
  --uri="$SERVICE_URL" \
  --http-method=POST \
  --oidc-service-account-email=your-service-account@$PROJECT_ID.iam.gserviceaccount.com \
  --oidc-token-audience="$SERVICE_URL" \
  --description="Auto-scrape Nintendo amiibo lineup"

echo "Cloud Scheduler job created!"
echo "The scraper will run every 6 hours automatically"
