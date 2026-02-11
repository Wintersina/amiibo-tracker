"""
Tests for service domain logic, particularly placeholder filtering.
"""
import pytest
from unittest.mock import Mock, MagicMock
from tracker.service_domain import AmiiboService


class TestAmiiboServicePlaceholderFiltering:
    """Test that placeholders are filtered from Google Sheets."""

    def test_seed_new_amiibos_skips_needs_backfill(self):
        """Test that amiibos with _needs_backfill flag are skipped."""
        # Mock the Google Sheet client
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            ["Amiibo ID", "Amiibo Name", "Game Series", "Release Date", "Type", "Collected Status"]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

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
                "_needs_backfill": True,  # Should be skipped
            },
        ]

        service.seed_new_amiibos(amiibos)

        # Verify only Mario was added (Luigi was skipped)
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Mario"

    def test_seed_new_amiibos_skips_placeholder_ids(self):
        """Test that amiibos with 00000000 IDs are skipped."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            ["Amiibo ID", "Amiibo Name", "Game Series", "Release Date", "Type", "Collected Status"]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

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
                "name": "Placeholder with 00000000 head",
                "head": "00000000",
                "tail": "02bb0e02",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
            {
                "name": "Placeholder with 00000000 tail",
                "head": "09d00301",
                "tail": "00000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
            },
        ]

        service.seed_new_amiibos(amiibos)

        # Only the real amiibo should be added
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Real Amiibo"

    def test_seed_new_amiibos_allows_backfilled(self):
        """Test that backfilled amiibos (no flag, real IDs) are added."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            ["Amiibo ID", "Amiibo Name", "Game Series", "Release Date", "Type", "Collected Status"]
        ]
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
                # No _needs_backfill flag - was removed after backfill
            }
        ]

        service.seed_new_amiibos(amiibos)

        # Should be added since it's backfilled
        mock_sheet.append_rows.assert_called_once()
        added_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(added_rows) == 1
        assert added_rows[0][1] == "Backfilled Amiibo"

    def test_seed_new_amiibos_logs_skipped_placeholders(self):
        """Test that skipped placeholders are logged."""
        mock_client = Mock()
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = [
            ["Amiibo ID", "Amiibo Name", "Game Series", "Release Date", "Type", "Collected Status"]
        ]
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

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
                "_needs_backfill": True,
            },
            {
                "name": "Placeholder 2",
                "head": "00000000",
                "tail": "00000000",
                "gameSeries": "Unknown",
                "type": "Figure",
                "release": {},
                "_needs_backfill": True,
            },
        ]

        # Mock the logger
        from unittest.mock import patch
        with patch.object(service, 'log_info') as mock_log:
            service.seed_new_amiibos(amiibos)

            # Verify logging was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert "placeholder" in call_args[0][0].lower()
            assert "2" in call_args[0][0]  # 2 placeholders skipped
