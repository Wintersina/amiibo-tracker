# Amiibo Tracker

Amiibo Tracker is a Django web app that keeps your personal Amiibo collection in sync with the public [Amiibo API](https://amiiboapi.com/). It reads and updates a Google Sheet so you can mark figures as collected and browse the catalog with search, filters, and dark mode.

## Features
- Pulls the latest Amiibo catalog and images from the Amiibo API
- Uses a Google Sheet as your private collection database
- Toggle collected status with one click
- Filters by game series and Amiibo type (cards and plushes are hidden by default)
- Dark mode, search, and collapsible sections for quick browsing

## Quick start
1. Install Python 3.11+ and create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```
2. Create a Google Service Account with access to Google Sheets and Google Drive. Download the `credentials.json` for that account and place it in the project root.
3. Make a Google Sheet named `AmiiboCollection` with headers `Amiibo ID | Amiibo Name | Collected Status`, then share it with the service account email.
4. Start the app locally:
   ```bash
   ./scripts/mac_local_run.sh
   ```
   On Windows use:
   ```bash
   ./scripts/windows_local_run.sh
   ```
5. Open [http://localhost:8000](http://localhost:8000) to browse and update your collection.

## Deployment
For production, the repository includes Terraform and GitHub Actions templates that deploy the app to Google Cloud Run. Provide your own Google Cloud project, OAuth client, and allowed hostnames (including custom domains like `goozamiibo.com`) when running the workflow or Terraform modules.

