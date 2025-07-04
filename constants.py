class OauthConstants:
    SCOPES = [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "openid",
    ]
    REDIRECT_URI = "http://localhost:8000/oauth2callback/"
