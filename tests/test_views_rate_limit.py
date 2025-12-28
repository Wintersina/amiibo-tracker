import json

import pytest
import requests
from django.test import RequestFactory
from gspread.exceptions import APIError

from tracker import views


def build_api_error(status=429, retry_after="15"):
    response = requests.Response()
    response.status_code = status
    response._content = b"rate limited"
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    api_error = APIError(response)
    api_error.code = status
    return api_error


def test_is_rate_limit_error_detects_429():
    assert views.is_rate_limit_error(build_api_error()) is True
    assert views.is_rate_limit_error(Exception("other")) is False


def test_retry_after_seconds_parses_header():
    api_error = build_api_error(retry_after="42")
    assert views.retry_after_seconds(api_error) == 42


def test_rate_limit_json_response_uses_retry_after():
    api_error = build_api_error(retry_after="9")
    response = views.rate_limit_json_response(api_error)

    assert response.status_code == 429
    payload = json.loads(response.content.decode())
    assert payload["retry_after"] == 9
    assert "rate limit" in payload["message"].lower()


def test_toggle_collected_returns_rate_limit(monkeypatch):
    api_error = build_api_error(retry_after="11")

    class DummyService:
        def __init__(self, **kwargs):
            del kwargs

        def toggle_collected(self, amiibo_id, action):
            assert amiibo_id == "abc"
            assert action == "collect"
            raise api_error

    class DummyManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(views, "AmiiboService", DummyService)
    monkeypatch.setattr(views, "GoogleSheetClientManager", DummyManager)

    rf = RequestFactory()
    request = rf.post(
        "/toggle/",
        data=json.dumps({"amiibo_id": "abc", "action": "collect"}),
        content_type="application/json",
    )
    request.session = {"credentials": {"token": "t"}}

    response = views.ToggleCollectedView.as_view()(request)

    assert response.status_code == 429
    payload = json.loads(response.content.decode())
    assert payload["status"] == "rate_limited"
    assert payload["retry_after"] == 11
