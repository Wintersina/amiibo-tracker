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
- `make clean` - Clean up cache files

## Deployment
For production, the repository includes Terraform and GitHub Actions templates that deploy the app to Google Cloud Run. Provide your own Google Cloud project, OAuth client, and allowed hostnames (including custom domains like `goozamiibo.com`) when running the workflow or Terraform modules.

> **Note on CSRF settings:** Django requires `CSRF_TRUSTED_ORIGINS` to include the fully-qualified HTTPS origins for the domains you serve. The production settings derive this list from `ALLOWED_HOSTS`, and Terraform passes the same list as an environment variable. Keep these values aligned with your custom domain (and the Cloud Run URL, if used) so OAuth callbacks and authenticated form submissions are accepted without 403 errors.

