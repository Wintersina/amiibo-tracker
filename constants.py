class OauthConstants:
    SCOPES = [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "openid",
    ]
    REDIRECT_URI = (
        "https://amiibo-tracker-106546309168.us-central1.run.app/oauth2callback/"
    )
