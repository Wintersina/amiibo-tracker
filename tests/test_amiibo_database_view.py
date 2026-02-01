import json

import pytest
from django.test import RequestFactory

from tracker import views


@pytest.fixture
def rf():
    return RequestFactory()


def test_filters_by_name_and_game_series(monkeypatch, rf):
    local_data = {
        "amiibo": [
            {
                "name": "Mario",
                "gameSeries": "Super Mario",
                "character": "Mario",
                "head": "00000000",
                "tail": "00000001",
            },
            {
                "name": "Link",
                "gameSeries": "The Legend of Zelda",
                "character": "Link",
                "head": "00000000",
                "tail": "00000002",
            },
        ]
    }

    monkeypatch.setattr(
        views.AmiiboDatabaseView,
        "_fetch_local_amiibos",
        lambda self: local_data["amiibo"],
    )
    monkeypatch.setattr(
        views.AmiiboDatabaseView, "_fetch_remote_amiibos", lambda self: []
    )

    request = rf.get("/api/amiibo/", {"name": "mar", "gameseries": "super"})
    response = views.AmiiboDatabaseView.as_view()(request)

    assert response.status_code == 200
    payload = json.loads(response.content.decode())
    assert payload["amiibo"] == [local_data["amiibo"][0]]


def test_character_filter_adds_usage(monkeypatch, rf):
    local_data = {
        "amiibo": [
            {
                "name": "Zelda",
                "gameSeries": "The Legend of Zelda",
                "character": "Zelda",
                "head": "ffff",
                "tail": "1111",
            }
        ]
    }
    remote_data = [
        {
            "name": "Zelda",
            "gameSeries": "The Legend of Zelda",
            "character": "Zelda",
            "head": "ffff",
            "tail": "1111",
            "gamesSwitch": [
                {"amiiboUsage": "Unlock costume", "gameName": "Breath of the Wild"}
            ],
        }
    ]

    monkeypatch.setattr(
        views.AmiiboDatabaseView,
        "_fetch_local_amiibos",
        lambda self: local_data["amiibo"],
    )
    monkeypatch.setattr(
        views.AmiiboDatabaseView, "_fetch_remote_amiibos", lambda self: remote_data
    )

    request = rf.get("/api/amiibo/", {"character": "zelda", "showusage": "1"})
    response = views.AmiiboDatabaseView.as_view()(request)

    assert response.status_code == 200
    payload = json.loads(response.content.decode())
    amiibos = payload["amiibo"]
    assert len(amiibos) == 1
    assert amiibos[0]["gamesSwitch"] == remote_data[0]["gamesSwitch"]


def test_logs_missing_remote_items(monkeypatch, rf):
    local_data = {
        "amiibo": [
            {
                "name": "Samus",
                "gameSeries": "Metroid",
                "character": "Samus",
                "head": "aaaa",
                "tail": "bbbb",
            }
        ]
    }
    remote_data = local_data["amiibo"] + [
        {
            "name": "Pikachu",
            "gameSeries": "Pokémon",
            "character": "Pikachu",
            "head": "cccc",
            "tail": "dddd",
        }
    ]

    log_calls = []

    def capture_log(self, message, **context):
        log_calls.append((message, context))

    monkeypatch.setattr(
        views.AmiiboDatabaseView,
        "_fetch_local_amiibos",
        lambda self: local_data["amiibo"],
    )
    monkeypatch.setattr(
        views.AmiiboDatabaseView, "_fetch_remote_amiibos", lambda self: remote_data
    )
    monkeypatch.setattr(views.AmiiboDatabaseView, "log_warning", capture_log)

    request = rf.get("/api/amiibo/")
    views.AmiiboDatabaseView.as_view()(request)

    assert any(
        call[0] == "amiibo-database-missing-items" and call[1]["missing_count"] == 1
        for call in log_calls
    )
