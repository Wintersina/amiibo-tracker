# Amiibo Tracker

This Django app allows you to track your personal Amiibo collection using a Google Sheet as a backend database. It
fetches the latest Amiibo list from the [Amiibo API](https://amiiboapi.com/) and lets you mark which ones you've
collected.

## Features

- Real-time sync with [Amiibo API](https://amiiboapi.com/)
- Google Sheet as a personal backend database
- Mark Amiibos as collected/uncollected with one click
- Amiibo images included
- This filters out, Card, Plush and others.

## Setup Instructions

1. **Clone the repo** (or extract the zip):
    ```bash
    git clone https://github.com/YOUR_USERNAME/amiibo-tracker.git
    cd amiibo-tracker
    ```

2. **Create a virtual environment and install dependencies**:
    ```bash
    python -m venv env
    source env/bin/activate  # or `env\Scripts\activate` on Windows
    pip install django gspread oauth2client requests
    ```

3. **Create a Google Service Account**:
    - Go to https://console.cloud.google.com/
    - Create a project, enable the **Google Sheets API** and **Google Drive API**
    - Create a service account and download the `credentials.json`
    - Share your Google Sheet with the service account’s email
    - example:
    - ```
      {
        "type": ***,
        "project_id": ***,
        "private_key_id": ***,
        "private_key": ***,
        "client_email": "@****.iam.gserviceaccount"
        "client_id": ***,
        "auth_uri": "https://accounts.google.com/o/oauth2
        "token_uri": "https://oauth2.googleapis.com
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/****.iam.gserviceaccount
        "universe_domain": "googleapis
      }
      ```

4. **Create a Google Sheet**:
    - Name it `AmiiboCollection`
    - Add the header `Amiibo ID` in the first row
    - Add the header `Amiibo Name` in the second row
    - Add the header `Collected Status` in the third row
    - click share and add your service account email to the sheet `"@****.iam.gserviceaccount"`


5. **Run the Django server**:
    ```bash
    python manage.py runserver
    ```

<h2> Example: </h2>

![img_2.png](img_2.png)
![img_3.png](img_3.png)