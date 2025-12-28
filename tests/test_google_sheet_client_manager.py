import json

import gspread
import pytest
import requests

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

    def del_worksheet(self, worksheet):
        self.worksheets.pop(worksheet.title, None)

    def worksheets_list(self):
        return list(self.worksheets.values())


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

    assert amiibo_sheet.rows == [
        [
            "Amiibo ID",
            "Amiibo Name",
            "Game Series",
            "Release Date",
            "Type",
            "Collected Status",
        ]
    ]
    assert config_sheet.rows == [
        ["Config name", "Config value"],
        ["DarkMode", "0"],
        ["IgnoreType:Band", "1"],
        ["IgnoreType:Card", "1"],
        ["IgnoreType:Yarn", "1"],
    ]
    assert manager.get_or_create_worksheet_by_name("AmiiboCollection") is amiibo_sheet


def test_open_or_create_spreadsheet_reuses_existing():
    existing_spreadsheet = object()

    class DummyClient:
        def open(self, name):
            self.opened = name
            return existing_spreadsheet

        def create(self, name):  # pragma: no cover - should not be called
            raise AssertionError("create should not be called when open succeeds")

    manager = GoogleSheetClientManager(sheet_name="ExistingSheet")
    manager.client = DummyClient()

    result = manager._open_or_create_spreadsheet()

    assert result is existing_spreadsheet
    assert manager.client.opened == "ExistingSheet"


def test_open_or_create_spreadsheet_creates_when_missing():
    created_spreadsheet = object()

    class DummyClient:
        def __init__(self):
            self.created = None

        def open(self, name):
            raise gspread.exceptions.SpreadsheetNotFound

        def create(self, name):
            self.created = name
            return created_spreadsheet

    manager = GoogleSheetClientManager(sheet_name="NewSheet")
    manager.client = DummyClient()
    manager.log_info = lambda *args, **kwargs: None

    result = manager._open_or_create_spreadsheet()

    assert result is created_spreadsheet
    assert manager.client.created == "NewSheet"


def test_open_or_create_spreadsheet_raises_on_create_failure():
    class DummyClient:
        def open(self, name):
            raise gspread.exceptions.SpreadsheetNotFound

        def create(self, name):
            response = requests.Response()
            response.status_code = 403
            response._content = b"permission denied"
            raise gspread.exceptions.APIError(response)

    manager = GoogleSheetClientManager(sheet_name="FailingSheet")
    manager.client = DummyClient()
    manager.log_error = lambda *args, **kwargs: None
    manager.log_info = lambda *args, **kwargs: None

    with pytest.raises(ValueError) as excinfo:
        manager._open_or_create_spreadsheet()

    assert "could not be created" in str(excinfo.value)


def test_initialize_default_worksheets_populates_missing():
    manager = GoogleSheetClientManager()
    spreadsheet = DummySpreadsheet()

    manager._initialize_default_worksheets(spreadsheet)

    amiibo_sheet = spreadsheet.worksheet(manager.work_sheet_amiibo_manager)
    config_sheet = spreadsheet.worksheet(manager.work_sheet_config_manager)

    assert amiibo_sheet.rows == [
        [
            "Amiibo ID",
            "Amiibo Name",
            "Game Series",
            "Release Date",
            "Type",
            "Collected Status",
        ]
    ]
    assert config_sheet.rows == [
        ["Config name", "Config value"],
        ["DarkMode", "0"],
        ["IgnoreType:Band", "1"],
        ["IgnoreType:Card", "1"],
        ["IgnoreType:Yarn", "1"],
    ]


def test_initialize_default_worksheets_respects_existing_data():
    manager = GoogleSheetClientManager()
    spreadsheet = DummySpreadsheet()
    spreadsheet.worksheets[manager.work_sheet_amiibo_manager] = DummyWorksheet(
        manager.work_sheet_amiibo_manager
    )
    spreadsheet.worksheets[manager.work_sheet_amiibo_manager].rows.append([
        "custom",
    ])
    spreadsheet.worksheets[manager.work_sheet_config_manager] = DummyWorksheet(
        manager.work_sheet_config_manager
    )
    spreadsheet.worksheets[manager.work_sheet_config_manager].rows.append([
        "config",
    ])

    manager._initialize_default_worksheets(spreadsheet)

    assert spreadsheet.worksheet(manager.work_sheet_amiibo_manager).rows == [["custom"]]
    assert spreadsheet.worksheet(manager.work_sheet_config_manager).rows == [["config"]]


def test_default_sheet_is_removed_after_initialization():
    manager = GoogleSheetClientManager()
    spreadsheet = DummySpreadsheet()
    spreadsheet.worksheets["Sheet1"] = DummyWorksheet("Sheet1")

    manager._initialize_default_worksheets(spreadsheet)

    assert "Sheet1" not in spreadsheet.worksheets
    assert set(spreadsheet.worksheets.keys()) == {
        manager.work_sheet_amiibo_manager,
        manager.work_sheet_config_manager,
    }
