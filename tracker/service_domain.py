import json
from functools import cached_property
from datetime import datetime
from pathlib import Path

from cachetools import TTLCache

from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.helpers import LoggingMixin, AmiiboRemoteFetchMixin, AmiiboLocalFetchMixin


class AmiiboService(LoggingMixin, AmiiboRemoteFetchMixin, AmiiboLocalFetchMixin):
    HEADER = [
        "Amiibo ID",
        "Amiibo Name",
        "Game Series",
        "Release Date",
        "Type",
        "Collected Status",
    ]
    COLLECTED_STATUS_COL = 6

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
        sheet = self.google_sheet_client.get_or_create_worksheet_by_name(
            self.work_sheet_title
        )
        self._ensure_sheet_structure(sheet)
        return sheet

    def fetch_amiibos(self):
        remote_amiibos = self._fetch_remote_amiibos()
        if remote_amiibos:
            return remote_amiibos

        return self._fetch_local_amiibos()

    def seed_new_amiibos(self, amiibos: list[dict]):
        existing_values = self.sheet.get_all_values()
        existing_map: dict[str, tuple[int, list[str]]] = {}
        for idx, row in enumerate(existing_values[1:], start=2):
            if row:
                existing_map[row[0]] = (idx, row)

        new_rows = []
        updates: dict[int, list[str]] = {}
        skipped_placeholders = []

        for amiibo in amiibos:
            # Skip placeholders that haven't been backfilled yet
            if amiibo.get("_needs_backfill"):
                skipped_placeholders.append(amiibo.get("name", "Unknown"))
                continue

            # Skip amiibos with placeholder IDs (00000000)
            if amiibo.get("head") == "00000000" or amiibo.get("tail") == "00000000":
                skipped_placeholders.append(amiibo.get("name", "Unknown"))
                continue

            amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
            release_date = self._format_release_date(amiibo.get("release"))

            if amiibo_id not in existing_map:
                new_rows.append(
                    [
                        amiibo_id,
                        amiibo["name"],
                        amiibo.get("gameSeries", ""),
                        release_date,
                        amiibo.get("type", ""),
                        "0",
                    ]
                )
                continue

            row_index, row = existing_map[amiibo_id]
            updated_row = list(row)
            if len(updated_row) < len(self.HEADER):
                updated_row.extend([""] * (len(self.HEADER) - len(updated_row)))

            changed = False
            if not updated_row[2] and amiibo.get("gameSeries"):
                updated_row[2] = amiibo.get("gameSeries", "")
                changed = True
            if not updated_row[3] and release_date:
                updated_row[3] = release_date
                changed = True
            if not updated_row[4] and amiibo.get("type"):
                updated_row[4] = amiibo.get("type", "")
                changed = True

            if changed:
                updates[row_index] = updated_row[: len(self.HEADER)]

        if updates:
            update_requests = [
                {"range": f"A{row_index}:F{row_index}", "values": [row_values]}
                for row_index, row_values in updates.items()
            ]
            self._batched_update(update_requests)

        if new_rows:
            self.sheet.append_rows(new_rows, value_input_option="USER_ENTERED")

        # Log skipped placeholders
        if skipped_placeholders:
            self.log_info(
                f"Skipped {len(skipped_placeholders)} placeholder amiibos (not backfilled yet)",
                placeholders=skipped_placeholders[:5],  # Show first 5
            )

    def get_collected_status(self):
        rows = self.sheet.get_all_values()[1:]
        return {
            row[0]: (
                row[self.COLLECTED_STATUS_COL - 1]
                if len(row) >= self.COLLECTED_STATUS_COL
                else "0"
            )
            for row in rows
        }

    def toggle_collected(self, amiibo_id: str, action: str):
        current_ids = self.sheet.col_values(1)[1:]
        if amiibo_id not in current_ids:
            return False

        cell = self.sheet.find(amiibo_id)
        self.sheet.update_cell(
            cell.row, self.COLLECTED_STATUS_COL, "1" if action == "collect" else "0"
        )
        return True

    def _ensure_sheet_structure(self, sheet):
        header = sheet.row_values(1)
        if header != self.HEADER:
            sheet.update("A1:F1", [self.HEADER])

    def _batched_update(self, update_requests: list[dict], batch_size: int = 50):
        batch_updater = getattr(self.sheet, "batch_update", None)

        for start in range(0, len(update_requests), batch_size):
            batch = update_requests[start : start + batch_size]
            if batch_updater:
                batch_updater(batch, value_input_option="USER_ENTERED")
            else:
                for request in batch:
                    self.sheet.update(request["range"], request["values"])

    @staticmethod
    def _format_release_date(release_info: dict | None):
        release_info = release_info or {}
        for region in ["na", "eu", "jp", "au"]:
            date_str = release_info.get(region)
            if date_str:
                try:
                    parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                    return parsed_date.strftime("%m/%d/%Y")
                except ValueError:
                    return date_str
        return None


class GoogleSheetConfigManager(LoggingMixin):
    CONFIG_HEADER = ["Config name", "Config value"]
    DEFAULT_IGNORE_TYPES = {"Band": "1", "Card": "1", "Yarn": "1"}
    _CONFIG_CACHE = TTLCache(maxsize=32, ttl=60)

    def __init__(
        self,
        google_sheet_client_manager: GoogleSheetClientManager,
        sheet_name="AmiiboCollection",
        work_sheet_title="AmiiboCollectionConfigManager",
    ):
        self.sheet_name = sheet_name
        self.work_sheet_title = work_sheet_title
        self.google_sheet_client: GoogleSheetClientManager = google_sheet_client_manager
        self._config_cache_key = (self.sheet_name, self.work_sheet_title)

    @cached_property
    def sheet(self):
        sheet = self.google_sheet_client.get_or_create_worksheet_by_name(
            self.work_sheet_title
        )
        self._ensure_structure(sheet)
        return sheet

    def is_dark_mode(self) -> bool:
        val = self.get_config_value("DarkMode", default="0")
        return val == "1"

    def set_dark_mode(self, enable: bool):
        self.set_config_value("DarkMode", "1" if enable else "0")

    def get_ignored_types(self, available_types: list[str]) -> list[str]:
        ignored_types = []
        for amiibo_type in available_types:
            key = self._type_config_key(amiibo_type)
            self._ensure_type_row(amiibo_type)
            if (
                self.get_config_value(
                    key, default=self._default_type_value(amiibo_type)
                )
                == "1"
            ):
                ignored_types.append(amiibo_type)
        return ignored_types

    def set_ignore_type(self, amiibo_type: str, ignore: bool):
        self._ensure_type_row(amiibo_type)
        self.set_config_value(
            self._type_config_key(amiibo_type), "1" if ignore else "0"
        )

    def get_config_value(self, key: str, default: str = "") -> str:
        config_map = self._get_config_map()
        if key in config_map:
            return config_map[key][1]
        return default

    def set_config_value(self, key: str, value: str):
        config_map = self._get_config_map()
        if key in config_map:
            row_index = config_map[key][0]
            self.sheet.update_cell(row_index, 2, value)
            config_map[key] = (row_index, value)
        else:
            self.sheet.append_row([key, value], value_input_option="USER_ENTERED")
            # next row is len(config_map) + 2 (account for header row)
            config_map[key] = (len(config_map) + 2, value)
        self._CONFIG_CACHE[self._config_cache_key] = config_map

    def _get_config_map(self) -> dict[str, tuple[int, str]]:
        if cached_map := self._CONFIG_CACHE.get(self._config_cache_key):
            return cached_map

        self._ensure_structure(self.sheet)
        values = self.sheet.get_all_values()
        config_map: dict[str, tuple[int, str]] = {}
        for idx, row in enumerate(values[1:], start=2):
            if not row or not row[0]:
                continue
            name = row[0]
            value = row[1] if len(row) > 1 else ""
            config_map[name] = (idx, value)

        self._CONFIG_CACHE[self._config_cache_key] = config_map
        return config_map

    def _ensure_structure(self, sheet):
        values = sheet.get_all_values()
        if not values or values[0][:2] != self.CONFIG_HEADER:
            existing_dark_mode = None
            if values and values[0] and values[0][0].lower() == "darkmode":
                existing_dark_mode = values[1][0] if len(values) > 1 else None

            sheet.clear()
            sheet.append_row(self.CONFIG_HEADER)
            dark_mode_value = existing_dark_mode or "0"
            defaults = [["DarkMode", dark_mode_value]]
            for amiibo_type, default_val in self.DEFAULT_IGNORE_TYPES.items():
                defaults.append([self._type_config_key(amiibo_type), default_val])
            sheet.append_rows(defaults, value_input_option="USER_ENTERED")
        else:
            # Ensure default rows exist
            config_map = {
                row[0]: idx for idx, row in enumerate(values[1:], start=2) if row
            }
            if "DarkMode" not in config_map:
                sheet.append_row(["DarkMode", "0"], value_input_option="USER_ENTERED")

            for amiibo_type, default_val in self.DEFAULT_IGNORE_TYPES.items():
                key = self._type_config_key(amiibo_type)
                if key not in config_map:
                    sheet.append_row(
                        [key, default_val], value_input_option="USER_ENTERED"
                    )
        if self._config_cache_key in self._CONFIG_CACHE:
            del self._CONFIG_CACHE[self._config_cache_key]

    def _type_config_key(self, amiibo_type: str) -> str:
        return f"IgnoreType:{amiibo_type}"

    def _ensure_type_row(self, amiibo_type: str):
        key = self._type_config_key(amiibo_type)
        default_value = self._default_type_value(amiibo_type)
        config_map = self._get_config_map()
        if key not in config_map:
            new_row_index = len(config_map) + 2
            self.sheet.append_row(
                [key, default_value], value_input_option="USER_ENTERED"
            )
            config_map[key] = (new_row_index, default_value)
            self._CONFIG_CACHE[self._config_cache_key] = config_map

    def _default_type_value(self, amiibo_type: str) -> str:
        return self.DEFAULT_IGNORE_TYPES.get(amiibo_type, "0")
