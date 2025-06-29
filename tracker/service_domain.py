from functools import cached_property

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials


class GoogleSheetClientManager:
    def __init__(
        self,
        sheet_name="AmiiboCollection",
        work_sheet_amiibo_manager="AmiiboCollection",
        work_sheet_config_manager="AmiiboCollectionConfigManager",
        credentials_file="credentials.json",
    ):
        self.sheet_name = sheet_name
        self.work_sheet_amiibo_manager = work_sheet_amiibo_manager
        self.work_sheet_config_manager = work_sheet_config_manager
        self.credentials_file = credentials_file

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

    @cached_property
    def client(self):
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            self.credentials_file, scope
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


class AmiiboService:
    def __init__(
        self, sheet_name="AmiiboCollection", work_sheet_title="AmiiboCollection"
    ):
        self.sheet_name = sheet_name
        self.work_sheet_title = work_sheet_title

    @cached_property
    def sheet(self):
        return GoogleSheetClientManager(
            sheet_name=self.sheet_name, work_sheet_amiibo_manager=self.work_sheet_title
        ).get_or_create_worksheet_by_name(self.work_sheet_title)

    def fetch_amiibos(self):
        response = requests.get("https://amiiboapi.com/api/amiibo/")
        return response.json().get("amiibo", [])

    def seed_new_amiibos(self, amiibos: list[dict]):
        existing_ids = self.sheet.col_values(1)[1:]
        new_rows = []

        for amiibo in amiibos:
            amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
            if amiibo_id not in existing_ids:
                new_rows.append([amiibo_id, amiibo["name"], "0"])

        if new_rows:
            self.sheet.append_rows(new_rows, value_input_option="USER_ENTERED")

    def get_collected_status(self):
        rows = self.sheet.get_all_values()[1:]
        return {row[0]: row[2] for row in rows}

    def toggle_collected(self, amiibo_id: str, action: str):
        current_ids = self.sheet.col_values(1)[1:]
        if amiibo_id not in current_ids:
            return False

        cell = self.sheet.find(amiibo_id)
        self.sheet.update_cell(cell.row, 3, "1" if action == "collect" else "0")
        return True


class GoogleSheetConfigManager:
    def __init__(
        self,
        sheet_name="AmiiboCollection",
        work_sheet_title="AmiiboCollectionConfigManager",
    ):
        self.sheet_name = sheet_name
        self.work_sheet_title = work_sheet_title

    @cached_property
    def sheet(self):
        return GoogleSheetClientManager(
            sheet_name=self.sheet_name, work_sheet_amiibo_manager=self.work_sheet_title
        ).get_or_create_worksheet_by_name(self.work_sheet_title)

    def is_dark_mode(self) -> bool:
        val = self.sheet.cell(2, 1).value
        return val == "1"

    def set_dark_mode(self, enable: bool):
        self.sheet.update_cell(2, 1, "1" if enable else "0")
