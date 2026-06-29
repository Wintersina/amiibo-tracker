# Amiibo Tracker

Amiibo Tracker is a Django web app that keeps your personal Amiibo collection in sync with the public [Amiibo API](https://amiiboapi.com/). It reads and updates a Google Sheet so you can mark figures as collected and browse the catalog with search, filters, and dark mode.

## Features
- Pulls the latest Amiibo catalog and images from the Amiibo API
- Uses a Google Sheet as your private collection database
- Toggle collected status with one click
- Filters by game series and Amiibo type (cards and plushes are hidden by default)
- Dark mode, search, and collapsible sections for quick browsing

## Quick start
1. **Prerequisites:** Install Python 3.11+ and Make.

2. **Setup development environment:**
   ```bash
   make dev-setup
   ```
   This will create a virtual environment (`env/`), install dependencies, and run database migrations.

3. **Create Google Service Account:**
   - Create a Google Service Account with access to Google Sheets and Google Drive
   - Download the `credentials.json` for that account and place it in the project root
   - Create a Google Sheet named `AmiiboCollection` with headers `Amiibo ID | Amiibo Name | Collected Status`
   - Share the sheet with the service account email

4. **Start the development server:**
   ```bash
   make run-local
   ```

5. Open [http://localhost:8080](http://localhost:8080) to browse and update your collection.

## Development Commands

Run `make help` to see all available commands, including:
- `make test` - Run all tests
- `make format` - Auto-format code
- `make lint` - Run linting checks
- `make scrape` - Run the amiibo scraper
- `make seed-prices` - Refresh AmiiboDex price snapshots when eBay API credentials are configured
- `make clean` - Clean up cache files

## AmiiboDex pricing

AmiiboDex always renders a direct eBay search link for each figure without any API token. The loose/NIB estimate column is optional and is populated only after a price refresh runs with eBay Browse API credentials.

For local seeding, put these values in `.env`:

```bash
EBAY_CLIENT_ID=your-ebay-client-id
EBAY_CLIENT_SECRET=your-ebay-client-secret
EBAY_MARKETPLACE_ID=EBAY_US
# Optional for eBay sandbox credentials:
EBAY_ENV=sandbox
```

Local page views skip Firestore pricing reads by default so AmiiboDex stays fast without Google credentials. For local UI testing, write prices to the gitignored JSON cache:

```bash
make seed-prices-local LIMIT=25
```

The cache lives at `tracker/data/amiibo_price_cache.local.json` and is ignored by git. Once that file exists, local AmiiboDex and detail pages read it automatically in development.

To test eBay credentials without saving to Firestore, run:

```bash
make seed-prices-dry LIMIT=1
```

To save snapshots to Firestore locally instead of the JSON cache, first authenticate Google Application Default Credentials for the Firestore project:

```bash
gcloud auth application-default login
```

Then run:

```bash
make seed-prices
make seed-prices LIMIT=25
```

If eBay credentials are missing, the command exits cleanly with `Skipped: ebay_credentials_missing`; the site still shows eBay listing links. If Firestore credentials are missing while saving, use `make seed-prices-dry` for an eBay-only test or configure Google ADC before saving.

Saved refreshes are idempotent per day: if an amiibo already has a price snapshot for the current refresh date, the command skips that amiibo instead of calling eBay or rewriting the same snapshot.

## Deployment
For production, the repository includes Terraform and GitHub Actions templates that deploy the app to Google Cloud Run. Provide your own Google Cloud project, OAuth client, and allowed hostnames (including custom domains like `goozamiibo.com`) when running the workflow or Terraform modules.

Production price refreshes use Cloud Scheduler and Secret Manager. Set GitHub Actions secrets `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET_SECRET`, where `EBAY_CLIENT_SECRET_SECRET` is the Secret Manager secret id containing the eBay client secret. Leave them empty to deploy without automated price estimates. The build workflow triggers one refresh after deployment, and Terraform creates a monthly Cloud Scheduler job (`0 5 1 * *` by default) that calls `/internal/refresh-prices` to store Firestore history snapshots.

For local OAuth testing, download the OAuth client JSON from Google Cloud Console and place it at `client_secret.json` in the repository root. The Docker Compose `dev` service mounts that file to `/app/client_secret.json`; use `docker compose up dev` for local OAuth testing. Add the exact local callback you use to the Google OAuth client's **Authorized redirect URIs**. Common values are `http://localhost:8000/oauth2callback/` for Django `runserver` and `http://localhost:8080/oauth2callback/` for the Docker Compose dev service. Use the same host in your browser that you registered in Google Cloud.

> **Note on CSRF settings:** Django requires `CSRF_TRUSTED_ORIGINS` to include the fully-qualified HTTPS origins for the domains you serve. The production settings derive this list from `ALLOWED_HOSTS`, and Terraform passes the same list as an environment variable. Keep these values aligned with your custom domain (and the Cloud Run URL, if used) so OAuth callbacks and authenticated form submissions are accepted without 403 errors.
