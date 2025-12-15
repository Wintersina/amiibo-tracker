import json

import gspread
import pytest

from tracker.google_sheet_client_manager import GoogleSheetClientManager


class DummyWorksheet:
    def __init__(self, title):
        self.title = title
        self.rows = []

    def append_row(self, row):
        self.rows.append(row)


class DummySpreadsheet:
    def __init__(self):
        self.worksheets = {}

    def worksheet(self, name):
        if name not in self.worksheets:
            raise gspread.exceptions.WorksheetNotFound
        return self.worksheets[name]

    def add_worksheet(self, title, rows, cols):
        del rows, cols  # unused in dummy implementation
        worksheet = DummyWorksheet(title)
        self.worksheets[title] = worksheet
        return worksheet


@pytest.fixture(autouse=True)
def reset_secret_cache():
    GoogleSheetClientManager._secret_path_cache = None
    yield
    GoogleSheetClientManager._secret_path_cache = None


def test_client_secret_path_writes_inline_secret(tmp_path, monkeypatch):
    inline_secret = {"installed": "client"}
    secret_file = tmp_path / "client_secret.json"

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS_DATA", json.dumps(inline_secret))
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", str(secret_file))

    path = GoogleSheetClientManager.client_secret_path()

    assert path == str(secret_file)
    assert secret_file.exists()
    assert json.loads(secret_file.read_text()) == inline_secret


def test_get_or_create_worksheet_by_name_creates_defaults():
    manager = GoogleSheetClientManager()
    manager.spreadsheet = DummySpreadsheet()

    amiibo_sheet = manager.get_or_create_worksheet_by_name("AmiiboCollection")
    config_sheet = manager.get_or_create_worksheet_by_name(
        "AmiiboCollectionConfigManager"
    )

    assert amiibo_sheet.rows == [["Amiibo ID", "Amiibo Name", "Collected Status"]]
    assert config_sheet.rows == [["DarkMode"], ["0"]]
    assert manager.get_or_create_worksheet_by_name("AmiiboCollection") is amiibo_sheet
