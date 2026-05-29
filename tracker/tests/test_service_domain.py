"""
Tests for service domain logic, particularly placeholder filtering.
"""

import pytest
from unittest.mock import Mock, MagicMock
from tracker.service_domain import AmiiboService


def mock_execute_worksheet_operation(func, *args, **kwargs):
    """Helper to make execute_worksheet_operation work in tests by calling the actual function."""
    return func(*args, **kwargs)


class TestAmiiboServicePlaceholderFiltering:
    """Test that placeholders are filtered from Google Sheets."""

    def test_seed_new_amiibos_skips_is_upcoming(self):
        """Test that amiibos with is_upcoming flag are skipped."""
        # Mock the Google Sheet client
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        # Test data with one placeholder
        amiibos = [
            {
                "name": "Mario",
                "head": "09d00301",  # Real ID
                "tail": "00000002",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2014-11-21"},
            },
            {
                "name": "Luigi",
                "head": "00000000",
                "tail": "00000000",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2026-03-15"},
                "is_upcoming": True,  # Should be skipped
            },
        ]

        service.seed_new_amiibos(amiibos)

        # Verify only Mario was added (Luigi was skipped)
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Mario"

    def test_seed_new_amiibos_includes_all_00000000_ids(self):
        """Test that amiibos with 00000000 IDs are ALWAYS included, regardless of release dates."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        amiibos = [
            {
                "name": "Real Amiibo",
                "head": "09d00301",
                "tail": "02bb0e02",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2014-11-21"},
            },
            {
                "name": "00000000 head without release",
                "head": "00000000",
                "tail": "02bb0e02",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
            {
                "name": "00000000 tail without release",
                "head": "09d00301",
                "tail": "00000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
        ]

        service.seed_new_amiibos(amiibos)

        # All three amiibos should be added (00000000 IDs are NEVER filtered)
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 3
        assert added_rows[0][1] == "Real Amiibo"
        assert added_rows[1][1] == "00000000 head without release"
        assert added_rows[2][1] == "00000000 tail without release"

    def test_seed_new_amiibos_allows_backfilled(self):
        """Test that backfilled amiibos (no flag, real IDs) are added."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        # Backfilled amiibo - no flag, real IDs
        amiibos = [
            {
                "name": "Backfilled Amiibo",
                "head": "09d00301",
                "tail": "02bb0e02",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2026-03-15"},
                "character": "Mario",
                "image": "https://example.com/mario.png",
                # No is_upcoming flag - amiibo is already released
            }
        ]

        service.seed_new_amiibos(amiibos)

        # Should be added since it's backfilled
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Backfilled Amiibo"

    def test_seed_new_amiibos_includes_released_with_placeholder_ids(self):
        """Test that released amiibos with 00000000 IDs are included (not filtered)."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        # 8-Bit Mario - has 00000000 head but is released
        amiibos = [
            {
                "name": "8-Bit Mario Classic Color",
                "head": "00000000",
                "tail": "02380602",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2015-09-11", "jp": "2015-09-10"},
                "is_upcoming": False,
            }
        ]

        service.seed_new_amiibos(amiibos)

        # Should be added despite 00000000 head because it has release dates
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "8-Bit Mario Classic Color"

    def test_seed_new_amiibos_skips_ff_placeholder_ids(self):
        """Test that amiibos with ff-prefixed IDs are skipped if they have no release dates."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        amiibos = [
            {
                "name": "Real Amiibo",
                "head": "09d00301",
                "tail": "02bb0e02",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "release": {"na": "2014-11-21"},
            },
            {
                "name": "FF Placeholder without release",
                "head": "ff000000",
                "tail": "02bb0e02",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
            {
                "name": "FF Placeholder tail without release",
                "head": "09d00301",
                "tail": "ff000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
        ]

        service.seed_new_amiibos(amiibos)

        # Only the real amiibo should be added (ff placeholders without release dates are filtered)
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Real Amiibo"

    def test_seed_new_amiibos_logs_skipped_placeholders(self):
        """Test that skipped placeholders are logged."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            [
                "Amiibo ID",
                "Amiibo Name",
                "Game Series",
                "Release Date",
                "Type",
                "Collected Status",
            ]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
        mock_client.execute_worksheet_operation.side_effect = mock_execute_worksheet_operation

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        amiibos = [
            {
                "name": "Placeholder 1",
                "head": "00000000",
                "tail": "00000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
                "is_upcoming": True,
            },
            {
                "name": "Placeholder 2",
                "head": "00000000",
                "tail": "00000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
                "is_upcoming": True,
            },
        ]

        # Mock the logger
        from unittest.mock import patch

        with patch.object(service, "log_info") as mock_log:
            service.seed_new_amiibos(amiibos)

            # Verify logging was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert "placeholder" in call_args[0][0].lower()
            assert "2" in call_args[0][0]  # 2 placeholders skipped


def _service_with_rows(rows):
    """Build an AmiiboService whose sheet returns the given values."""
    mock_client = Mock()
    mock_sheet = MagicMock()
    mock_sheet.get_all_values.return_value = rows
    mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet
    mock_client.execute_worksheet_operation.side_effect = (
        mock_execute_worksheet_operation
    )
    service = AmiiboService(mock_client)
    service.sheet = mock_sheet
    return service, mock_sheet


class TestAmiiboServiceFavorites:
    """Favorite column read/write behavior (column G)."""

    HEADER_7 = [
        "Amiibo ID",
        "Amiibo Name",
        "Game Series",
        "Release Date",
        "Type",
        "Collected Status",
        "Favorite",
    ]

    def test_new_rows_include_favorite_default(self):
        """Seeded rows carry a 7th column defaulting the Favorite flag to '0'."""
        service, mock_sheet = _service_with_rows([self.HEADER_7])
        service.seed_new_amiibos(
            [
                {
                    "name": "Mario",
                    "head": "09d00301",
                    "tail": "02bb0e02",
                    "gameSeries": "Super Mario",
                    "type": "Figure",
                    "release": {"na": "2014-11-21"},
                }
            ]
        )
        added = mock_sheet.append_rows.call_args[0][0][0]
        assert len(added) == 7
        assert added[5] == "0"  # collected
        assert added[6] == "0"  # favorite

    def test_get_favorite_status_reads_column_g(self):
        service, _ = _service_with_rows(
            [
                self.HEADER_7,
                ["idA", "A", "S", "", "Figure", "1", "1"],
                ["idB", "B", "S", "", "Figure", "1", "0"],
                ["idC", "C", "S", "", "Figure", "0"],  # legacy 6-col row
            ]
        )
        favorites = service.get_favorite_status()
        assert favorites == {"idA": "1", "idB": "0", "idC": "0"}

    def test_combined_status_reads_once(self):
        service, mock_sheet = _service_with_rows(
            [
                self.HEADER_7,
                ["idA", "A", "S", "", "Figure", "1", "0"],
                ["idB", "B", "S", "", "Figure", "0", "1"],
            ]
        )
        collected, favorite = service.get_collected_and_favorite_status()
        assert collected == {"idA": "1", "idB": "0"}
        assert favorite == {"idA": "0", "idB": "1"}
        # Single read of the sheet for both maps.
        assert mock_sheet.get_all_values.call_count == 1

    def test_toggle_favorite_writes_column_g(self):
        service, mock_sheet = _service_with_rows(
            [self.HEADER_7, ["idA", "A", "S", "", "Figure", "0", "0"]]
        )
        mock_sheet.col_values.return_value = ["Amiibo ID", "idA"]
        mock_sheet.find.return_value = Mock(row=2)

        assert service.toggle_favorite("idA", "favorite") is True
        mock_sheet.update_cell.assert_called_once_with(2, 7, "1")

        mock_sheet.update_cell.reset_mock()
        assert service.toggle_favorite("idA", "unfavorite") is True
        mock_sheet.update_cell.assert_called_once_with(2, 7, "0")

    def test_toggle_favorite_missing_amiibo_returns_false(self):
        service, mock_sheet = _service_with_rows([self.HEADER_7])
        mock_sheet.col_values.return_value = ["Amiibo ID"]
        assert service.toggle_favorite("missing", "favorite") is False
        mock_sheet.update_cell.assert_not_called()

    def test_ensure_structure_widens_legacy_six_column_sheet(self):
        """Migrating a 6-column sheet adds the missing column before writing."""
        service = AmiiboService(Mock())
        mock_sheet = MagicMock()
        mock_sheet.col_count = 6
        mock_sheet.row_values.return_value = self.HEADER_7[:6]  # legacy header
        service.google_sheet_client.execute_worksheet_operation.side_effect = (
            mock_execute_worksheet_operation
        )

        service._ensure_sheet_structure(mock_sheet)

        mock_sheet.add_cols.assert_called_once_with(1)
        mock_sheet.update.assert_called_once_with("A1:G1", [self.HEADER_7])
