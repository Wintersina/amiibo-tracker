class OauthConstants:
    SCOPES = [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    # Google must receive the exact redirect_uri registered in the OAuth
    # client configuration. Hardcode the production callback so the login flow
    # never falls back to an outdated path.
    REDIRECT_URI = "https://goozamiibo.com/oauth2callback/"
