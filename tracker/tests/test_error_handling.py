"""
Tests for Google Sheets error handling and conversion.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from django.test import override_settings
from gspread.exceptions import APIError
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.service_domain import AmiiboService
from tracker.exceptions import (
    InsufficientScopesError,
    SpreadsheetPermissionError,
    QuotaExceededError,
    SpreadsheetNotFoundError,
    RateLimitError,
    InvalidCredentialsError,
    ServiceUnavailableError,
)


class MockResponse:
    """Mock response object for APIError."""

    def __init__(self, status_code, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        """Mock json method that gspread's APIError expects."""
        return {
            "error": {
                "code": self.status_code,
                "message": self.text,
                "status": "UNKNOWN",
            }
        }


class TestExecuteWorksheetOperation:
    """Test that execute_worksheet_operation properly converts APIErrors to GoogleSheetsErrors."""

    def test_insufficient_scopes_error_conversion(self):
        """Test that 403 with 'insufficient authentication scopes' raises InsufficientScopesError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        # Mock operation that raises APIError with insufficient scopes message
        def failing_operation():
            response = MockResponse(403, text="Request had insufficient authentication scopes.")
            error = APIError(response)
            raise error

        with pytest.raises(InsufficientScopesError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "grant access to Google Drive and Google Sheets" in exc_info.value.user_message
        assert exc_info.value.action_required == "reauth_required"
        assert not exc_info.value.is_retryable

    def test_quota_exceeded_error_conversion(self):
        """Test that 403 with 'quota' or 'limit' raises QuotaExceededError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def failing_operation():
            response = MockResponse(403, text="Quota exceeded for quota metric.")
            error = APIError(response)
            raise error

        with pytest.raises(QuotaExceededError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "quota" in exc_info.value.user_message.lower()
        assert exc_info.value.action_required == "wait_24h"

    def test_permission_error_conversion(self):
        """Test that 403 without specific keywords raises SpreadsheetPermissionError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def failing_operation():
            error = APIError(MockResponse(403))
            error.args = ("APIError: [403]: Permission denied.",)
            raise error

        with pytest.raises(SpreadsheetPermissionError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "permission" in exc_info.value.user_message.lower()
        assert exc_info.value.action_required == "logout_required"

    def test_not_found_error_conversion(self):
        """Test that 404 raises SpreadsheetNotFoundError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def failing_operation():
            error = APIError(MockResponse(404))
            raise error

        with pytest.raises(SpreadsheetNotFoundError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "could not be found" in exc_info.value.user_message.lower()

    def test_rate_limit_error_conversion(self):
        """Test that 429 raises RateLimitError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def failing_operation():
            error = APIError(MockResponse(429, headers={"Retry-After": "60"}))
            raise error

        with pytest.raises(RateLimitError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "rate limit" in exc_info.value.user_message.lower()
        assert exc_info.value.retry_after == 60
        assert exc_info.value.is_retryable

    def test_invalid_credentials_error_conversion(self):
        """Test that 401 raises InvalidCredentialsError."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def failing_operation():
            error = APIError(MockResponse(401))
            raise error

        with pytest.raises(InvalidCredentialsError) as exc_info:
            manager.execute_worksheet_operation(failing_operation)

        assert "expired" in exc_info.value.user_message.lower()

    def test_successful_operation(self):
        """Test that successful operations return the expected result."""
        manager = GoogleSheetClientManager(creds_json={"token": "test"})

        def successful_operation(x, y):
            return x + y

        result = manager.execute_worksheet_operation(successful_operation, 5, 3)
        assert result == 8


class TestServiceErrorPropagation:
    """Test that service methods properly propagate errors from worksheet operations."""

    def test_toggle_collected_insufficient_scopes(self):
        """Test that toggle_collected propagates InsufficientScopesError."""
        mock_client = Mock()
        mock_sheet = MagicMock()

        # Mock execute_worksheet_operation to raise InsufficientScopesError
        def raise_insufficient_scopes(*args, **kwargs):
            raise InsufficientScopesError()

        mock_client.execute_worksheet_operation.side_effect = raise_insufficient_scopes
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        with pytest.raises(InsufficientScopesError):
            service.toggle_collected("test_id", "collect")

    def test_seed_new_amiibos_permission_error(self):
        """Test that seed_new_amiibos propagates SpreadsheetPermissionError."""
        mock_client = Mock()
        mock_sheet = MagicMock()

        def raise_permission_error(*args, **kwargs):
            raise SpreadsheetPermissionError("test_spreadsheet")

        mock_client.execute_worksheet_operation.side_effect = raise_permission_error
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        amiibos = [
            {
                "name": "Test Amiibo",
                "head": "09d00301",
                "tail": "02bb0e02",
                "gameSeries": "Test",
                "type": "Figure",
                "release": {"na": "2024-01-01"},
            }
        ]

        with pytest.raises(SpreadsheetPermissionError):
            service.seed_new_amiibos(amiibos)

    def test_get_collected_status_rate_limit(self):
        """Test that get_collected_status propagates RateLimitError."""
        mock_client = Mock()
        mock_sheet = MagicMock()

        def raise_rate_limit(*args, **kwargs):
            raise RateLimitError(retry_after=30)

        mock_client.execute_worksheet_operation.side_effect = raise_rate_limit
        mock_client.get_or_create_worksheet_by_name.return_value = mock_sheet

        service = AmiiboService(mock_client)
        service.sheet = mock_sheet

        with pytest.raises(RateLimitError) as exc_info:
            service.get_collected_status()

        assert exc_info.value.retry_after == 30


class TestOAuthCallbackErrorHandling:
    """Test that OAuthCallbackView handles errors gracefully."""

    @override_settings(ALLOWED_HOSTS=['*', 'testserver', 'localhost'])
    @patch("tracker.views.build_sheet_client_manager")
    @patch("tracker.views.ensure_spreadsheet_session")
    @patch("tracker.views.Flow")
    @patch("tracker.views.googleapiclient")
    def test_oauth_callback_insufficient_scopes_redirects(
        self, mock_googleapiclient, mock_flow, mock_ensure_spreadsheet, mock_build_manager
    ):
        """Test that insufficient scopes error redirects to index with error message."""
        from django.test import RequestFactory
        from tracker.views import OAuthCallbackView

        # Setup
        factory = RequestFactory()
        request = factory.get("/oauth-callback?code=test_code&state=test_state")
        request.session = {
            "oauth_state": "test_state",
            "oauth_code_verifier": "test_verifier",
        }

        # Mock Flow to avoid OAuth flow
        mock_flow_instance = Mock()
        # Include all required scopes so it passes the scope check
        mock_flow_instance.credentials = Mock(scopes=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ])
        mock_flow.from_client_secrets_file.return_value = mock_flow_instance

        # Mock user info
        mock_userinfo = Mock()
        mock_userinfo.get.return_value.execute.return_value = {
            "name": "Test User",
            "email": "test@example.com",
        }
        mock_googleapiclient.discovery.build.return_value.userinfo.return_value = mock_userinfo

        # Mock to raise InsufficientScopesError when building manager
        mock_build_manager.side_effect = InsufficientScopesError()

        view = OAuthCallbackView()
        response = view.get(request)

        # Should redirect to index
        assert response.status_code == 302
        assert "index" in response.url or response.url == "/"

        # Should store error in session
        assert "oauth_error" in request.session
        assert "grant access" in request.session["oauth_error"]["message"].lower()
        assert request.session["oauth_error"]["action_required"] == "reauth_required"

    @override_settings(ALLOWED_HOSTS=['*', 'testserver', 'localhost'])
    @patch("tracker.views.build_sheet_client_manager")
    @patch("tracker.views.ensure_spreadsheet_session")
    @patch("tracker.views.Flow")
    @patch("tracker.views.googleapiclient")
    def test_oauth_callback_permission_error_clears_session(
        self, mock_googleapiclient, mock_flow, mock_ensure_spreadsheet, mock_build_manager
    ):
        """Test that permission errors clear OAuth session data."""
        from django.test import RequestFactory
        from tracker.views import OAuthCallbackView

        # Setup
        factory = RequestFactory()
        request = factory.get("/oauth-callback?code=test_code&state=test_state")
        request.session = {
            "credentials": {"token": "test"},
            "user_name": "Test User",
            "user_email": "test@example.com",
            "oauth_state": "test_state",
            "oauth_code_verifier": "test_verifier",
        }

        # Mock Flow
        mock_flow_instance = Mock()
        mock_flow_instance.credentials = Mock(scopes=["required_scope"])
        mock_flow.from_client_secrets_file.return_value = mock_flow_instance

        # Mock user info
        mock_userinfo = Mock()
        mock_userinfo.get.return_value.execute.return_value = {
            "name": "Test User",
            "email": "test@example.com",
        }
        mock_googleapiclient.discovery.build.return_value.userinfo.return_value = mock_userinfo

        # Mock to raise SpreadsheetPermissionError
        mock_build_manager.side_effect = SpreadsheetPermissionError("test_id")

        view = OAuthCallbackView()
        response = view.get(request)

        # Should clear sensitive session data
        assert "credentials" not in request.session
        assert "user_name" not in request.session
        assert "user_email" not in request.session
        assert "oauth_state" not in request.session
