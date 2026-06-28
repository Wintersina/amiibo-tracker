import os


class OauthConstants:
    SCOPES = [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    DEFAULT_REDIRECT_URI = "https://goozamiibo.com/oauth2callback/"
    REDIRECT_URI = DEFAULT_REDIRECT_URI

    @classmethod
    def configured_redirect_uri(cls):
        # Google must receive a redirect_uri registered in the OAuth client.
        # Production sets OAUTH_REDIRECT_URI through Terraform; local runs can
        # override it or let the request-aware view helper build localhost.
        return os.environ.get("OAUTH_REDIRECT_URI") or cls.DEFAULT_REDIRECT_URI
