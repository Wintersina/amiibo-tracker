import os
from functools import cached_property

import gspread
from django.conf import settings
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from oauth2client.service_account import ServiceAccountCredentials
from cachetools import TTLCache

from constants import OauthConstants
from tracker.helpers import HelperMixin, LoggingMixin


class GoogleSheetClientManager(HelperMixin, LoggingMixin):
    _secret_path_cache = None
    _spreadsheet_cache = TTLCache(maxsize=8, ttl=60)
    _worksheet_cache = TTLCache(maxsize=16, ttl=60)

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
        spreadsheet_id=None,
    ):
        self.sheet_name = sheet_name
        self.work_sheet_amiibo_manager = work_sheet_amiibo_manager
        self.work_sheet_config_manager = work_sheet_config_manager
        self.credentials_file = credentials_file or "credentials.json"
        self.creds_json = creds_json
        self.spreadsheet_id = spreadsheet_id

    @cached_property
    def spreadsheet(self):
        cache_key = self._spreadsheet_cache_key()
        if cache_key in self._spreadsheet_cache:
            return self._spreadsheet_cache[cache_key]

        spreadsheet = self._open_or_create_spreadsheet()
        self.spreadsheet_id = spreadsheet.id
        cache_key = self._spreadsheet_cache_key()
        self._initialize_default_worksheets(spreadsheet)
        self._spreadsheet_cache[cache_key] = spreadsheet
        return spreadsheet

    def _open_or_create_spreadsheet(self):
        if self.spreadsheet_id:
            try:
                return self.client.open_by_key(self.spreadsheet_id)
            except gspread.exceptions.SpreadsheetNotFound:
                self.log_warning(
                    "Stored spreadsheet id '%s' was not found; falling back to discovery by name.",
                    self.spreadsheet_id,
                )

        if existing_spreadsheet := self._find_existing_spreadsheet_by_name():
            return existing_spreadsheet

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

    def _find_existing_spreadsheet_by_name(self):
        try:
            spreadsheets = self.client.list_spreadsheet_files()
        except Exception as error:  # gspread can surface multiple exception types
            self.log_warning(
                "Unable to list accessible spreadsheets for '%s': %s",
                self.sheet_name,
                error,
            )
            return None

        for spreadsheet in spreadsheets:
            if spreadsheet.get("name") != self.sheet_name:
                continue

            try:
                return self.client.open_by_key(spreadsheet.get("id"))
            except gspread.exceptions.SpreadsheetNotFound:
                self.log_warning(
                    "Spreadsheet id '%s' for '%s' was not found during lookup.",
                    spreadsheet.get("id"),
                    self.sheet_name,
                )
                continue

        return None

    def _initialize_default_worksheets(self, spreadsheet):
        self._get_or_create_worksheet(spreadsheet, self.work_sheet_amiibo_manager)
        self._get_or_create_worksheet(spreadsheet, self.work_sheet_config_manager)
        self._remove_default_sheet_if_present(spreadsheet)

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

    def _get_or_create_worksheet(self, spreadsheet, worksheet_name):
        cache_key = self._worksheet_cache_key(spreadsheet.id, worksheet_name)
        if cache_key in self._worksheet_cache:
            return self._worksheet_cache[cache_key]

        try:
            sheet = spreadsheet.worksheet(worksheet_name)
            created = False
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=worksheet_name, rows=500, cols=6)
            created = True

        if created:
            if worksheet_name == self.work_sheet_amiibo_manager:
                sheet.append_row(
                    [
                        "Amiibo ID",
                        "Amiibo Name",
                        "Game Series",
                        "Release Date",
                        "Type",
                        "Collected Status",
                    ]
                )

            if worksheet_name == self.work_sheet_config_manager:
                sheet.append_row(["Config name", "Config value"])
                sheet.append_row(["DarkMode", "0"])
                sheet.append_row(["IgnoreType:Band", "1"])
                sheet.append_row(["IgnoreType:Card", "1"])
                sheet.append_row(["IgnoreType:Yarn", "1"])

        self._worksheet_cache[cache_key] = sheet
        return sheet

    def get_or_create_worksheet_by_name(self, worksheet_name):
        return self._get_or_create_worksheet(self.spreadsheet, worksheet_name)

    def _remove_default_sheet_if_present(self, spreadsheet):
        try:
            default_sheet = spreadsheet.worksheet("Sheet1")
        except gspread.exceptions.WorksheetNotFound:
            return

        managed_titles = {
            self.work_sheet_amiibo_manager,
            self.work_sheet_config_manager,
        }

        if default_sheet.title in managed_titles:
            return

        if hasattr(spreadsheet, "del_worksheet"):
            spreadsheet.del_worksheet(default_sheet)

    def _spreadsheet_cache_key(self) -> tuple[str, str, bool, str | None]:
        return (
            self.sheet_name,
            self.credentials_file,
            bool(self.creds_json),
            self.spreadsheet_id,
        )

    @staticmethod
    def _worksheet_cache_key(spreadsheet_id: str, worksheet_name: str) -> tuple[str, str]:
        return (spreadsheet_id, worksheet_name)
