# Scripts

This directory contains utility scripts for managing the amiibo tracker infrastructure.

## setup-scraper-scheduler.sh

**Purpose**: Idempotent script to create or update the Cloud Scheduler job for the Nintendo amiibo scraper.

### Features

- ✅ **Idempotent**: Safe to run multiple times - won't fail if job already exists
- ✅ **Auto-configures**: Automatically gets Cloud Run URL and service account
- ✅ **CI/CD ready**: Runs automatically in GitHub Actions pipeline
- ✅ **Customizable**: Override schedule and timezone via environment variables

### Usage

#### Basic Usage (with defaults)

```bash
export PROJECT_ID="your-project-id"
bash scripts/setup-scraper-scheduler.sh
```

#### With Custom Schedule

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export SERVICE_NAME="amiibo-tracker"
export SCHEDULE="0 */12 * * *"  # Every 12 hours
export TIMEZONE="America/New_York"

bash scripts/setup-scraper-scheduler.sh
```

#### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROJECT_ID` | ✅ Yes | - | Google Cloud project ID |
| `REGION` | No | `us-central1` | Cloud Run region |
| `SERVICE_NAME` | No | `amiibo-tracker` | Cloud Run service name |
| `SCHEDULE` | No | `0 */6 * * *` | Cron schedule expression |
| `TIMEZONE` | No | `America/Los_Angeles` | Timezone for scheduler |

### Schedule Examples

```bash
# Every 6 hours (default)
SCHEDULE="0 */6 * * *"

# Every 12 hours
SCHEDULE="0 */12 * * *"

# Daily at 3 AM
SCHEDULE="0 3 * * *"

# Twice daily (9 AM and 9 PM)
SCHEDULE="0 9,21 * * *"

# Every hour
SCHEDULE="0 * * * *"

# Every Monday at 8 AM
SCHEDULE="0 8 * * 1"
```

### What It Does

1. Validates required environment variables
2. Gets the Cloud Run service URL
3. Configures the appropriate service account
4. Enables Cloud Scheduler API if needed
5. Creates or updates the scheduler job
6. Displays job details and test commands

### CI/CD Integration

This script runs automatically in the GitHub Actions pipeline after deploying to Cloud Run:

- **Workflow**: `.github/workflows/build.yml`
- **Step**: "Setup Nintendo Scraper Scheduler"
- **Trigger**: Automatically after every deployment to `main` branch

### Manual Trigger via GitHub Actions

You can also trigger just the scheduler setup without deploying:

1. Go to **Actions** tab
2. Select **"Setup/Update Scraper Scheduler"** workflow
3. Click **"Run workflow"**
4. Customize schedule/timezone if needed
5. Click **"Run workflow"**

### Troubleshooting

#### Error: "Could not find Cloud Run service"

Make sure the Cloud Run service is deployed first:

```bash
gcloud run services list --project=$PROJECT_ID --region=$REGION
```

#### Error: "App Engine required"

Cloud Scheduler requires an App Engine app (no compute resources). The script will automatically create one.

#### Permission Errors

Ensure your service account has these roles:
- `roles/cloudscheduler.admin`
- `roles/run.invoker`
- `roles/iam.serviceAccountUser`

### Testing the Scheduler

After setup, test the job manually:

```bash
# Trigger the job now
gcloud scheduler jobs run nintendo-amiibo-scraper \
  --location=$REGION \
  --project=$PROJECT_ID

# View job details
gcloud scheduler jobs describe nintendo-amiibo-scraper \
  --location=$REGION \
  --project=$PROJECT_ID

# View execution history
gcloud scheduler jobs describe nintendo-amiibo-scraper \
  --location=$REGION \
  --project=$PROJECT_ID \
  --format="table(lastAttemptTime, status.message)"
```

### Logs

Check Cloud Run logs to see scraper execution:

```bash
# View recent logs
gcloud run services logs read amiibo-tracker \
  --region=$REGION \
  --project=$PROJECT_ID \
  --limit=50

# Filter for scraper logs
gcloud run services logs read amiibo-tracker \
  --region=$REGION \
  --project=$PROJECT_ID \
  --filter="textPayload:scraper"
```

Or view in Cloud Console:
- [Cloud Run Logs](https://console.cloud.google.com/run)
- [Cloud Scheduler Jobs](https://console.cloud.google.com/cloudscheduler)
