from functools import cached_property

import google.auth  # Import google.auth
import gspread
from google.oauth2.credentials import Credentials

from constants import OauthConstants


class GoogleSheetClientManager:

    def __init__(
        self,
        sheet_name="AmiiboCollection",
        work_sheet_amiibo_manager="AmiiboCollection",
        work_sheet_config_manager="AmiiboCollectionConfigManager",
        creds_json=None,
    ):
        self.sheet_name = sheet_name
        self.work_sheet_amiibo_manager = work_sheet_amiibo_manager
        self.work_sheet_config_manager = work_sheet_config_manager
        self.creds_json = creds_json

        try:
            self.spreadsheet = self.client.open(sheet_name)

        except gspread.exceptions.SpreadsheetNotFound:
            print(f"Spreadsheet '{sheet_name}' not found. Creating a new spreadsheet.")
            self.spreadsheet = self.client.create(sheet_name)

            print(
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

        print(f"Successfully initialized with spreadsheet '{self.spreadsheet.title}'")

    @staticmethod
    def get_flow():
        # This method is for OAuth 2.0 (user authentication flow), which is not what you want for server-to-server
        # authentication with a service account. You can likely remove it or mark it as deprecated.
        raise NotImplementedError(
            "This method is for local user-based OAuth flow and not for cloud deployment."
        )

    @cached_property
    def client(self):

        if self.creds_json:
            creds = Credentials.from_authorized_user_info(
                self.creds_json, OauthConstants.SCOPES
            )
            client = gspread.authorize(creds)
        else:

            credentials, project = google.auth.default(scopes=OauthConstants.SCOPES)
            client = gspread.authorize(credentials)
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
