import os
from unittest.mock import Mock, patch

from django.test import RequestFactory, override_settings

from tracker.views import OAuthView, oauth_redirect_uri_for_request


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
