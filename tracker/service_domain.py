from functools import cached_property

import requests
from googleapiclient.discovery import build

from tracker.google_sheet_client_manager import GoogleSheetClientManager


class AmiiboService:
    def __init__(
        self,
        google_sheet_client_manager,
        sheet_name="AmiiboCollection",
        work_sheet_title="AmiiboCollection",
    ):
        self.sheet_name = sheet_name
        self.work_sheet_title = work_sheet_title
        self.google_sheet_client: GoogleSheetClientManager = google_sheet_client_manager

    @cached_property
    def sheet(self):
        return self.google_sheet_client.get_or_create_worksheet_by_name(
            self.work_sheet_title
        )

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
        google_sheet_client_manager,
        sheet_name="AmiiboCollection",
        work_sheet_title="AmiiboCollectionConfigManager",
    ):
        self.sheet_name = sheet_name
        self.work_sheet_title = work_sheet_title
        self.google_sheet_client: GoogleSheetClientManager = google_sheet_client_manager

    @cached_property
    def sheet(self):
        return self.google_sheet_client.get_or_create_worksheet_by_name(
            self.work_sheet_title
        )

    def is_dark_mode(self) -> bool:
        val = self.sheet.cell(2, 1).value
        return val == "1"

    def set_dark_mode(self, enable: bool):
        self.sheet.update_cell(2, 1, "1" if enable else "0")
