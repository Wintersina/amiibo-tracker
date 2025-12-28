from tracker.service_domain import AmiiboService


class DummySheet:
    def __init__(self):
        self.rows = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ],
            [
                "existingseriesexistingtail",
                "Existing Amiibo",
                "series",
                "",
                "Figure",
                "0",
            ],
        ]
        self.append_rows_calls = []
        self.update_calls = []

    def col_values(self, index):
        return [row[index - 1] for row in self.rows]

    def row_values(self, index):
        return self.rows[index - 1] if index - 1 < len(self.rows) else []

    def append_rows(self, rows, value_input_option=None):
        self.append_rows_calls.append((rows, value_input_option))
        self.rows.extend(rows)

    def update(self, cell_range, rows):
        self.update_calls.append((cell_range, rows))
        for idx, row in enumerate(rows, start=1):
            if idx - 1 < len(self.rows):
                self.rows[idx - 1] = row
            else:
                self.rows.append(row)

    def get_all_values(self):
        return self.rows

    def find(self, value):
        for idx, row in enumerate(self.rows, start=1):
            if row[0] == value:
                return type("Cell", (), {"row": idx})
        raise ValueError("Not found")

    def update_cell(self, row, col, value):
        self.rows[row - 1][col - 1] = value


def build_service():
    class DummyClient:
        def __init__(self):
            self.sheet = DummySheet()

        def get_or_create_worksheet_by_name(self, name):
            return self.sheet

    return AmiiboService(DummyClient())


def test_seed_new_amiibos_appends_missing_rows():
    service = build_service()
    new_amiibos = [
        {
            "head": "new",
            "gameSeries": "series",
            "tail": "tail",
            "name": "New",
            "type": "Figure",
        },
        {
            "head": "existing",
            "gameSeries": "series",
            "tail": "existingtail",
            "name": "Existing Amiibo",
            "type": "Figure",
        },
    ]

    service.seed_new_amiibos(new_amiibos)

    assert ["newseriestail", "New", "series", None, "Figure", "0"] in service.sheet.rows
    assert len(service.sheet.append_rows_calls) == 1
    # ensure the existing amiibo was not duplicated
    assert service.sheet.rows.count(
        ["existingseriesexistingtail", "Existing Amiibo", "series", "", "Figure", "0"]
    ) == 1


def test_toggle_collected_updates_known_id():
    service = build_service()

    assert service.toggle_collected("missing-id", "collect") is False

    updated = service.toggle_collected("existingseriesexistingtail", "collect")

    assert updated is True
    assert service.sheet.rows[1][5] == "1"


def test_ensure_sheet_structure_sets_expected_header():
    service = build_service()
    # corrupt header to ensure update is called
    service.sheet.rows[0] = ["Old Header"]

    service._ensure_sheet_structure(service.sheet)

    assert service.sheet.rows[0] == AmiiboService.HEADER
    assert service.sheet.update_calls == [("A1:F1", [AmiiboService.HEADER])]


def test_seed_new_amiibos_formats_release_date():
    service = build_service()
    amiibos = [
        {
            "head": "rel",
            "gameSeries": "series",
            "tail": "date",
            "name": "Release Amiibo",
            "type": "Figure",
            "release": {"na": "2024-05-10"},
        }
    ]

    service.seed_new_amiibos(amiibos)

    assert [
        "relseriesdate",
        "Release Amiibo",
        "series",
        "05/10/2024",
        "Figure",
        "0",
    ] in service.sheet.rows
