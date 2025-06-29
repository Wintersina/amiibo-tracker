from functools import cached_property

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials


class AmiiboService:
    def __init__(self, sheet_name="AmiiboCollection", credentials_file="credentials.json"):
        self.sheet_name = sheet_name
        self.credentials_file = credentials_file

    @cached_property
    def sheet(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_file, scope)
        client = gspread.authorize(creds)
        return client.open(self.sheet_name).sheet1

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
