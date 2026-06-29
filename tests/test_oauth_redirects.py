import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, override_settings

from constants import OauthConstants
from tracker import views
from tracker.views import OAuthCallbackView, OAuthView, oauth_redirect_uri_for_request


def test_oauth_redirect_uri_uses_local_request_host(monkeypatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://goozamiibo.com/oauth2callback/")
    monkeypatch.delenv("OAUTHLIB_INSECURE_TRANSPORT", raising=False)

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="localhost:8000")

    assert oauth_redirect_uri_for_request(request) == (
        "http://localhost:8000/oauth2callback/"
    )
    assert os.environ["OAUTHLIB_INSECURE_TRANSPORT"] == "1"


@override_settings(DEBUG=False)
def test_oauth_redirect_uri_uses_configured_non_canonical_production_uri(monkeypatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://example.com/oauth2callback/")

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="preview.example.com")

    assert oauth_redirect_uri_for_request(request) == (
        "https://example.com/oauth2callback/"
    )


@override_settings(DEBUG=False)
def test_oauth_redirect_uri_for_canonical_site_ignores_stale_local_env(monkeypatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8080/oauth2callback/")

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="goozamiibo.com")

    assert oauth_redirect_uri_for_request(request) == (
        "https://goozamiibo.com/oauth2callback/"
    )


@override_settings(DEBUG=False)
def test_oauth_redirect_uri_for_production_falls_back_from_stale_local_env(monkeypatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8080/oauth2callback/")

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="service.run.app")

    assert oauth_redirect_uri_for_request(request) == (
        "https://goozamiibo.com/oauth2callback/"
    )


@patch("tracker.views.logout_user")
@patch("tracker.views.get_active_credentials_json", return_value=None)
@patch("tracker.views.GoogleSheetClientManager.client_secret_path")
@patch("tracker.views.Flow")
def test_oauth_login_flow_receives_local_redirect_uri(
    mock_flow,
    mock_client_secret_path,
    mock_get_active_credentials_json,
    mock_logout_user,
    monkeypatch,
):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://goozamiibo.com/oauth2callback/")
    mock_client_secret_path.return_value = "/tmp/client_secret.json"
    flow_instance = Mock()
    flow_instance.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth",
        "state-token",
    )
    flow_instance.code_verifier = "code-verifier"
    mock_flow.from_client_secrets_file.return_value = flow_instance

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="localhost:8000")
    request.session = {}

    response = OAuthView().get(request)

    assert response.status_code == 302
    assert mock_flow.from_client_secrets_file.call_args.kwargs["redirect_uri"] == (
        "http://localhost:8000/oauth2callback/"
    )
    assert request.session["oauth_state"] == "state-token"
    assert request.session["oauth_code_verifier"] == "code-verifier"


@patch("tracker.views.logout_user")
@patch("tracker.views.get_active_credentials_json", return_value=None)
@patch("tracker.views.GoogleSheetClientManager.client_secret_path")
@patch("tracker.views.Flow")
def test_oauth_login_missing_client_secret_redirects_with_setup_error(
    mock_flow,
    mock_client_secret_path,
    mock_get_active_credentials_json,
    mock_logout_user,
):
    mock_client_secret_path.return_value = "/app/client_secret.json"
    mock_flow.from_client_secrets_file.side_effect = FileNotFoundError(
        "/app/client_secret.json"
    )

    request = RequestFactory().get("/oauth-login/", HTTP_HOST="localhost:8080")
    request.session = {}

    response = OAuthView().get(request)

    assert response.status_code == 302
    assert response.url == "/"
    assert request.session["oauth_error"]["action_required"] == "oauth_config_required"


def test_initialize_tracking_sheet_for_login_seeds_public_amiibos(monkeypatch):
    seeded = []
    manager = object()

    class DummyService:
        def __init__(self, google_sheet_client_manager):
            assert google_sheet_client_manager is manager

        def fetch_amiibos(self):
            return [
                {
                    "name": "Mario",
                    "head": "00000000",
                    "tail": "00000002",
                    "gameSeries": "Super Mario",
                    "amiiboSeries": "Super Smash Bros.",
                    "type": "Figure",
                },
                {
                    "name": "Unsupported",
                    "head": "ffffffff",
                    "tail": "ffffffff",
                    "gameSeries": "Pragmata",
                    "amiiboSeries": "Pragmata",
                    "type": "Figure",
                },
            ]

        def seed_new_amiibos(self, amiibos):
            seeded.extend(amiibos)

    monkeypatch.setattr(views, "AmiiboService", DummyService)

    request = RequestFactory().get("/oauth2callback/")
    request.session = {}

    summary = views.initialize_tracking_sheet_for_login(request, manager)

    assert [amiibo["name"] for amiibo in seeded] == ["Mario"]
    assert summary == {"seeded_amiibo_count": 1}
    assert request.session["tracking_sheet_ready"] is True


@override_settings(ALLOWED_HOSTS=["*", "testserver", "localhost"])
@patch("tracker.views.initialize_tracking_sheet_for_login")
@patch("tracker.views.build_sheet_client_manager")
@patch("tracker.views.ensure_spreadsheet_session")
@patch("tracker.views.Flow")
@patch("tracker.views.googleapiclient")
def test_oauth_callback_initializes_tracking_sheet_before_redirect(
    mock_googleapiclient,
    mock_flow,
    mock_ensure_spreadsheet,
    mock_build_manager,
    mock_initialize_tracking_sheet,
):
    credentials = SimpleNamespace(
        token="token",
        refresh_token="refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=OauthConstants.SCOPES,
        expiry=None,
    )
    flow_instance = Mock()
    flow_instance.credentials = credentials
    mock_flow.from_client_secrets_file.return_value = flow_instance

    userinfo = Mock()
    userinfo.get.return_value.execute.return_value = {
        "name": "Test User",
        "email": "test@example.com",
    }
    mock_googleapiclient.discovery.build.return_value.userinfo.return_value = userinfo

    manager = Mock()
    mock_build_manager.return_value = manager
    mock_initialize_tracking_sheet.return_value = {"seeded_amiibo_count": 42}

    request = RequestFactory().get(
        "/oauth2callback/?code=test-code&state=test-state",
        HTTP_HOST="testserver",
    )
    request.session = {
        "oauth_state": "test-state",
        "oauth_code_verifier": "verifier",
    }

    response = OAuthCallbackView().get(request)

    assert response.status_code == 302
    assert response.url == "/tracker/"
    mock_ensure_spreadsheet.assert_called_once_with(request, manager)
    mock_initialize_tracking_sheet.assert_called_once_with(request, manager)
    assert request.session["user_email"] == "test@example.com"
