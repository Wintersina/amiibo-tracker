class OauthConstants:
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://spreadsheets.google.com/feeds",
    ]
    REDIRECT_URI = "http://localhost:8000/oauth2callback/"
