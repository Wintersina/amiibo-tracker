from tracker.service_domain import AmiiboService


class DummySheet:
    def __init__(self):
        self.rows = [
            ["Amiibo ID", "Amiibo Name", "Collected Status"],
            ["existingseriesexistingtail", "Existing Amiibo", "0"],
        ]
        self.append_rows_calls = []

    def col_values(self, index):
        return [row[index - 1] for row in self.rows]

    def append_rows(self, rows, value_input_option=None):
        self.append_rows_calls.append((rows, value_input_option))
        self.rows.extend(rows)

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
        {"head": "new", "gameSeries": "series", "tail": "tail", "name": "New"},
        {
            "head": "existing",
            "gameSeries": "series",
            "tail": "existingtail",
            "name": "Existing Amiibo",
        },
    ]

    service.seed_new_amiibos(new_amiibos)

    assert ["newseriestail", "New", "0"] in service.sheet.rows
    assert len(service.sheet.append_rows_calls) == 1
    # ensure the existing amiibo was not duplicated
    assert service.sheet.rows.count(
        ["existingseriesexistingtail", "Existing Amiibo", "0"]
    ) == 1


def test_toggle_collected_updates_known_id():
    service = build_service()

    assert service.toggle_collected("missing-id", "collect") is False

    updated = service.toggle_collected("existingseriesexistingtail", "collect")

    assert updated is True
    assert service.sheet.rows[1][2] == "1"
