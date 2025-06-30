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
# for local run
export OAUTHLIB_INSECURE_TRANSPORT=1
python manage.py runserver
```

Visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## 🧹 Code Formatting with Black

We use [`black`](https://github.com/psf/black) to auto-format all Python code.

### Format all Python files

```bash
black .
```

### Optional: Set up Black as a Git pre-commit hook

Install `pre-commit`:

```bash
pip install pre-commit
```

Create a `.pre-commit-config.yaml` file in your project root:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.4.2  # Use the latest stable version
    hooks:
      - id: black
```

Then initialize the pre-commit hook:

```bash
pre-commit install
```

Run it manually on all files:

```bash
pre-commit run --all-files
```

From now on, Black will automatically format your code every time you commit.

---

## 🖼️ Example Screenshots

![img_2.png](img_2.png)  
![img_3.png](img_3.png)  
![img.png](img.png)

---