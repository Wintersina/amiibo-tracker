import os
from functools import cached_property

import gspread
from django.conf import settings
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from oauth2client.service_account import ServiceAccountCredentials

from constants import OauthConstants
from tracker.helpers import HelperMixin, LoggingMixin


class GoogleSheetClientManager(HelperMixin, LoggingMixin):
    _secret_path_cache = None

    @classmethod
    def client_secret_path(cls) -> str:
        inline_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_DATA")
        target_path = os.environ.get(
            "GOOGLE_OAUTH_CLIENT_SECRETS",
            os.path.join(settings.BASE_DIR, "client_secret.json"),
        )

        if inline_secret:
            if cls._secret_path_cache:
                return cls._secret_path_cache

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as secret_file:
                secret_file.write(inline_secret)
            cls._secret_path_cache = target_path

        return target_path

    def __init__(
        self,
        sheet_name="AmiiboCollection",
        work_sheet_amiibo_manager="AmiiboCollection",
        work_sheet_config_manager="AmiiboCollectionConfigManager",
        credentials_file=None,
        creds_json=None,
    ):
        self.sheet_name = sheet_name
        self.work_sheet_amiibo_manager = work_sheet_amiibo_manager
        self.work_sheet_config_manager = work_sheet_config_manager
        self.credentials_file = credentials_file or "credentials.json"
        self.creds_json = creds_json

    @cached_property
    def spreadsheet(self):
        try:
            return self.client.open(self.sheet_name)

        except gspread.exceptions.SpreadsheetNotFound:
            self.log_info(
                "Spreadsheet '%s' not found; attempting to create it with Drive file access.",
                self.sheet_name,
            )

            try:
                return self.client.create(self.sheet_name)
            except gspread.exceptions.APIError as error:
                message = (
                    f"Spreadsheet '{self.sheet_name}' was not found and could not be created. "
                    "Please ensure the app has the 'Google Drive file' permission so it can create files it owns."
                )
                self.log_error("%s Error: %s", message, error)
                raise ValueError(message) from error

    def get_creds(self, creds_json) -> Credentials:
        creds = Credentials.from_authorized_user_info(creds_json, OauthConstants.SCOPES)
        return creds

    @staticmethod
    def get_flow() -> Flow:
        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
        )
        return flow

    @cached_property
    def client(self):
        if oauth_creds := self.get_creds(self.creds_json):
            return gspread.authorize(oauth_creds)
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            self.credentials_file, OauthConstants.SCOPES
        )
        client = gspread.authorize(creds)
        return client

    def get_or_create_worksheet_by_name(self, worksheet_name):
        try:
            sheet = self.spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = self.spreadsheet.add_worksheet(
                title=worksheet_name, rows=500, cols=3
            )

            if worksheet_name == "AmiiboCollection":
                sheet.append_row(["Amiibo ID", "Amiibo Name", "Collected Status"])

            if worksheet_name == "AmiiboCollectionConfigManager":
                sheet.append_row(["DarkMode"])
                sheet.append_row(["0"])

        return sheet
