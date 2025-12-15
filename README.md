# Amiibo Tracker

This Django app allows you to track your personal Amiibo collection using a Google Sheet as a backend database. It
fetches the latest Amiibo list from the [Amiibo API](https://amiiboapi.com/) and lets you mark which ones you've
collected.

---

## ✨ Features

- Real-time sync with [Amiibo API](https://amiiboapi.com/)
- Google Sheet as a personal backend database
- Mark Amiibos as collected/uncollected with one click
- Amiibo images included
- Filters out cards, plushes, and other non-standard Amiibos
- Dark mode, filters, search, and collapsible game series sections
- Code formatting enforced using `black` and optional Git pre-commit hook

---

## 🚀 Setup Instructions

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/amiibo-tracker.git
cd amiibo-tracker
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv env
source env/bin/activate  # or `env\Scripts\activate` on Windows
pip install -r requirements.txt  # or install manually:
pip install django gspread oauth2client requests black pre-commit
```

---

### 3. Create a Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the following APIs:
   - **Google Sheets API**
   - **Google Drive API**
3. Create a **Service Account**
4. Download the `credentials.json` file and place it in your project root
5. Share your Google Sheet with the service account's email

Example format of `credentials.json`:

```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "your-service-account@your-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account@your-project.iam.gserviceaccount.com"
}
```

---

### 4. Create your Google Sheet

- Name it **`AmiiboCollection`**
- Add the following headers in row 1:
  ```
  Amiibo ID | Amiibo Name | Collected Status
  ```
- Share the sheet with your service account's email (`...@...iam.gserviceaccount.com`)

---

### 5. Run the Django development server

```bash
./scripts/mac_local_run.sh
```
for windows
```bash
./scripts/windows_local_run.sh
```

Visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## ☁️ Deploying to Google Cloud Run with Terraform

The repository includes Terraform configuration to provision the minimum Google Cloud resources for Cloud Run and Artifact Registry. You still need to supply your OAuth client JSON via Secret Manager and provide the Docker image URL to deploy.

1. **Prerequisites**
   - [gcloud CLI](https://cloud.google.com/sdk/docs/install)
   - [Terraform](https://developer.hashicorp.com/terraform/downloads)
   - Google Cloud project with billing enabled
   - OAuth client secret stored in Secret Manager (latest version will be injected into the service)

2. **Build and push the container image**
   ```bash
   gcloud builds submit --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/amiibo-tracker/amiibo-tracker:latest"
   ```

3. **Store your OAuth client secret in Secret Manager**
   ```bash
   # Save your OAuth client JSON locally first, then upload it
   gcloud secrets create amiibo-tracker-oauth-client --replication-policy="automatic"
   gcloud secrets versions add amiibo-tracker-oauth-client --data-file="path/to/client_secret.json"
   ```
   The secret name (`amiibo-tracker-oauth-client` above) is passed to Terraform via `-var="oauth_client_secret_secret=..."`.

4. **Bootstrap Terraform**
   ```bash
   cd terraform
   terraform init
   ```

5. **Apply infrastructure**
   ```bash
   terraform apply \
     -var="project_id=${PROJECT_ID}" \
     -var="region=${REGION}" \
     -var="image_url=${REGION}-docker.pkg.dev/${PROJECT_ID}/amiibo-tracker/amiibo-tracker:latest" \
     -var="django_secret_key=${DJANGO_SECRET_KEY}" \
     -var="allowed_hosts=${ALLOWED_HOSTS_AS_JSON_LIST}" \
     -var="oauth_redirect_uri=${OAUTH_REDIRECT_URI}" \
     -var="oauth_client_secret_secret=${SECRET_MANAGER_NAME}" \
     -var="client_secret_path=/secrets/client_secret.json"
   ```

6. **Review outputs**
   Terraform will print the Cloud Run URL after a successful apply. Use it to update your OAuth redirect URI and to access the deployed app.

### Environment variables used at runtime

| Variable | Purpose |
| --- | --- |
| `ENV_NAME` | Automatically set to `production` in Terraform deployments. |
| `DJANGO_SECRET_KEY` | Secret key for Django. **Required.** |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts for Django. |
| `OAUTH_REDIRECT_URI` | OAuth redirect URI registered in Google Cloud Console. |
| `GOOGLE_OAUTH_CLIENT_SECRETS` | Optional filesystem path to the OAuth client JSON; defaults to `client_secret.json` at the project root. |
| `GOOGLE_OAUTH_CLIENT_SECRETS_DATA` | Optional inline OAuth client JSON (injected from Secret Manager via Terraform). If set, the JSON is written to `GOOGLE_OAUTH_CLIENT_SECRETS` and used by the app. |



## 🖼️ Example Screenshots

![img_2.png](img_2.png)  
![img_3.png](img_3.png)  
![img.png](img.png)

---