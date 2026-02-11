# Nintendo Amiibo Scraper Setup for Cloud Run

## Overview

The scraper automatically fetches new amiibos from Nintendo's website and updates your database. Since your app runs on Google Cloud Run (serverless), we use **Google Cloud Scheduler** to trigger the scraper periodically.

## Architecture

```
Cloud Scheduler → POST /api/scrape-nintendo/ → Scraper runs → Updates JSON → Done
     (every 6 hours)
```

## 🚀 Quick Setup (Automated CI/CD)

**The scheduler is automatically configured in your CI/CD pipeline!**

Just push your code to `main` branch:

```bash
git add .
git commit -m "Add Nintendo amiibo scraper"
git push origin main
```

The GitHub Actions workflow will:
1. ✅ Build and push Docker image
2. ✅ Deploy to Cloud Run
3. ✅ **Automatically create/update the Cloud Scheduler job**

That's it! The scraper will run every 6 hours automatically.

---

## Manual Setup (Alternative)

If you need to set up the scheduler manually or customize settings:

### 1. Deploy Your App to Cloud Run

Make sure your latest code with the scraper is deployed:

```bash
# Push to trigger CI/CD
git push origin main

# Or deploy manually
gcloud run deploy amiibo-tracker \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

### 2. Test the Scraper Endpoint

```bash
# Get your Cloud Run URL
export SERVICE_URL=$(gcloud run services describe your-service-name \
  --region us-central1 \
  --format 'value(status.url)')

# Test the scraper (GET for info)
curl $SERVICE_URL/api/scrape-nintendo/

# Trigger the scraper (POST to run)
curl -X POST $SERVICE_URL/api/scrape-nintendo/
```

### 3. Setup Cloud Scheduler

#### Option A: Using the Setup Script (Idempotent - Recommended)

```bash
# Run the automated setup script
bash scripts/setup-scraper-scheduler.sh

# Or with custom schedule
export SCHEDULE="0 */12 * * *"  # Every 12 hours
export TIMEZONE="America/New_York"
bash scripts/setup-scraper-scheduler.sh
```

The script is **idempotent** - safe to run multiple times. It will:
- ✅ Create the job if it doesn't exist
- ✅ Update the job if it already exists
- ✅ Verify the service URL
- ✅ Configure the service account

#### Option B: Using GitHub Actions Workflow

Manually trigger the scheduler setup from GitHub:

1. Go to **Actions** tab in your GitHub repo
2. Select **"Setup/Update Scraper Scheduler"** workflow
3. Click **"Run workflow"**
4. Optionally customize:
   - Schedule (default: `0 */6 * * *`)
   - Timezone (default: `America/Los_Angeles`)
5. Click **"Run workflow"**

#### Option C: Using gcloud CLI

```bash
# Set your project ID
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export SERVICE_URL="https://your-app.run.app"

# Create scheduler job
gcloud scheduler jobs create http nintendo-amiibo-scraper \
  --location=$REGION \
  --schedule="0 */6 * * *" \
  --uri="$SERVICE_URL/api/scrape-nintendo/" \
  --http-method=POST \
  --oidc-service-account-email=your-service-account@$PROJECT_ID.iam.gserviceaccount.com \
  --description="Auto-scrape Nintendo amiibo lineup every 6 hours"

# Test the job manually
gcloud scheduler jobs run nintendo-amiibo-scraper --location=$REGION
```

#### Option D: Using Google Cloud Console

1. Go to [Cloud Scheduler](https://console.cloud.google.com/cloudscheduler)
2. Click **Create Job**
3. Fill in:
   - **Name**: `nintendo-amiibo-scraper`
   - **Region**: Same as your Cloud Run service
   - **Frequency**: `0 */6 * * *` (every 6 hours)
   - **Timezone**: Your preferred timezone
   - **Target**: HTTP
   - **URL**: `https://your-app.run.app/api/scrape-nintendo/`
   - **HTTP Method**: POST
   - **Auth header**: OIDC token with your service account
4. Click **Create**

### 4. Schedule Options

Adjust the cron schedule as needed:

```bash
# Every 6 hours
0 */6 * * *

# Every 12 hours
0 */12 * * *

# Daily at 3 AM
0 3 * * *

# Twice daily (9 AM and 9 PM)
0 9,21 * * *

# Every hour (if you need real-time updates)
0 * * * *
```

## Manual Triggering

You can also trigger the scraper manually:

### From Command Line

```bash
python manage.py scrape_nintendo_amiibos --dry-run
python manage.py scrape_nintendo_amiibos
```

### Via API

```bash
curl -X POST https://your-app.run.app/api/scrape-nintendo/
```

### From Cloud Run Console

1. Go to Cloud Scheduler
2. Select `nintendo-amiibo-scraper`
3. Click **Run Now**

## Monitoring

### View Logs

```bash
# Cloud Scheduler logs
gcloud scheduler jobs describe nintendo-amiibo-scraper --location=$REGION

# Cloud Run logs
gcloud run services logs read your-service-name \
  --region=$REGION \
  --limit=50 \
  --format="table(timestamp, textPayload)"

# Filter for scraper logs
gcloud run services logs read your-service-name \
  --region=$REGION \
  --filter="textPayload:scraper" \
  --limit=20
```

### Check Scraper Status

```bash
# Check the API endpoint
curl https://your-app.run.app/api/scrape-nintendo/

# Response:
# {
#   "status": "ready",
#   "endpoint": "POST to this URL to trigger scraper",
#   "info": "Designed for Google Cloud Scheduler"
# }
```

## How It Works

1. **Cloud Scheduler** triggers the `/api/scrape-nintendo/` endpoint every 6 hours
2. **Scraper** checks if it's been 6+ hours since last run (based on file modification time)
3. If yes, it:
   - Scrapes Nintendo's amiibo lineup page
   - Matches amiibos by name (substring matching)
   - Updates release dates for existing amiibos
   - Creates placeholders for new amiibos (with `_needs_backfill: true`)
4. **Updates** the `amiibo_database.json` file
5. **Returns** JSON response with statistics

## Important Notes for Cloud Run

### File Persistence

⚠️ **Important**: Cloud Run's filesystem is ephemeral. Changes to `amiibo_database.json` will persist during the instance lifetime but may be lost on redeployment.

**Solutions**:

1. **Commit JSON to Git** (simplest - recommended for now)
   - Manually commit updated JSON periodically
   - Or use a GitHub Actions workflow to auto-commit

2. **Use Cloud Storage** (more robust)
   - Store JSON in Google Cloud Storage bucket
   - Modify scraper to read/write from GCS

3. **Use Google Sheets as Source of Truth** (you already have this!)
   - Modify scraper to update Google Sheets directly
   - Your app already uses Google Sheets

### Cache Strategy

The scraper uses **file modification time** for caching (not in-memory cache) because Cloud Run instances spin down/up. This means:

- ✅ Cache persists across requests to the same instance
- ✅ Prevents running scraper multiple times in short period
- ⚠️ New instances will see old modification time from deployment
- ✅ `force=True` parameter bypasses cache check

## Troubleshooting

### Scraper not running

```bash
# Check Cloud Scheduler job
gcloud scheduler jobs describe nintendo-amiibo-scraper --location=$REGION

# Check if job is paused
gcloud scheduler jobs update nintendo-amiibo-scraper \
  --location=$REGION \
  --resume
```

### Permission errors

Make sure your service account has the right permissions:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:your-service-account@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

### Check recent runs

```bash
# View recent scheduler runs
gcloud scheduler jobs describe nintendo-amiibo-scraper \
  --location=$REGION \
  --format="table(lastAttemptTime, status.message)"
```

## Cost Estimation

- **Cloud Scheduler**: $0.10 per job per month + $0.10 per execution (3 free jobs included)
- **Cloud Run**: Minimal cost (~$0.01 per scraper run)
- **Total**: ~$0.50-$1.00 per month for 4 runs per day

## Next Steps

Consider migrating to Cloud Storage or updating Google Sheets directly for better persistence:

```python
# Future enhancement: Update Google Sheets directly
# The scraper could use your existing GoogleSheetClientManager
# to write directly to the AmiiboCollection sheet
```
