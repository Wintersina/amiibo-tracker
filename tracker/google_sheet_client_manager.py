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
    CLIENT_SECRETS = os.path.join(settings.BASE_DIR, "client_secret.json")

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
        self.credentials_file = (credentials_file or "credentials.json",)
        self.creds_json = creds_json

        try:
            self.spreadsheet = self.client.open(sheet_name)

        except gspread.exceptions.SpreadsheetNotFound:
            self.log_info(
                f"Spreadsheet '{sheet_name}' not found. Creating a new spreadsheet."
            )
            self.spreadsheet = self.client.create(sheet_name)

            self.log_info(
                f"Creating worksheet '{self.work_sheet_amiibo_manager}' within the new spreadsheet."
            )
            self.work_sheet_amiibo_manager_object = self.spreadsheet.add_worksheet(
                title=self.work_sheet_amiibo_manager, rows=500, cols=3
            )
            self.work_sheet_config_manager_object = self.spreadsheet.add_worksheet(
                title=self.work_sheet_config_manager, rows=500, cols=3
            )

            # create header for sheet1
            self.work_sheet_amiibo_manager_object.append_row(
                ["Amiibo ID", "Amiibo Name", "Collected Status"]
            )

            # create header and default value for sheet 2
            self.work_sheet_config_manager_object.append_row(["DarkMode"])
            self.work_sheet_config_manager_object.append_row(["0"])

        self.log_info(
            f"Successfully initialized with spreadsheet '{self.spreadsheet.title}'"
        )

    def get_creds(self, creds_json) -> Credentials:
        creds = Credentials.from_authorized_user_info(creds_json, OauthConstants.SCOPES)
        return creds

    @staticmethod
    def get_flow() -> Flow:
        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.CLIENT_SECRETS,
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
        )
        return flow

    @cached_property
    def client(self):
        if oauth_creds := self.get_creds(self.creds_json):
            # this uses web
            return gspread.authorize(oauth_creds)
        else:
            # this grabs using service account file

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

            # todo make this a better constant and fetch
            if worksheet_name == "AmiiboCollection":
                sheet.append_row(["Amiibo ID", "Amiibo Name", "Collected Status"])

            if worksheet_name == "AmiiboCollectionConfigManager":
                sheet.append_row(["DarkMode"])
                sheet.append_row(["0"])

        return sheet
