# Amiibo Tracker

This Django app allows you to track your personal Amiibo collection using a Google Sheet as a backend database. It fetches the latest Amiibo list from the [Amiibo API](https://amiiboapi.com/) and lets you mark which ones you've collected.

## Features

- Real-time sync with [Amiibo API](https://amiiboapi.com/)
- Google Sheet as a personal backend database
- Mark Amiibos as collected/uncollected with one click
- Amiibo images included

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

4. **Create a Google Sheet**:
    - Name it `AmiiboCollection`
    - Add the header `Amiibo ID` in the first row

5. **Run the Django server**:
    ```bash
    python manage.py runserver
    ```

## License

MIT License
