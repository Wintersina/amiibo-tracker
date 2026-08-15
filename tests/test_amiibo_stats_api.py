"""Tests for /api/amiibo-stats/ and its shared-secret gate.

This endpoint returns data rather than firing a side effect, so unlike the other
API views it must never answer without a valid token.
"""

import pytest
from django.conf import settings as django_settings
from django.test import Client, override_settings
from django.urls import reverse

from tracker import amiibo_report, firestore_client


ENDPOINT = "/api/amiibo-stats/"
SECRET = "a-real-secret-key-for-tests"

# The suite's other view tests pin ALLOWED_HOSTS the same way.
settings_override = override_settings(ALLOWED_HOSTS=["testserver"], SECRET_KEY=SECRET)


@pytest.fixture(autouse=True)
def _pinned_settings(monkeypatch):
    monkeypatch.delenv("AMIIBO_STATS_TOKEN", raising=False)
    settings_override.enable()
    yield
    settings_override.disable()


@pytest.fixture
def token():
    return amiibo_report.api_token()


@pytest.fixture
def fake_report(monkeypatch):
    monkeypatch.setattr(
        amiibo_report,
        "build_report",
        lambda top=10: {
            "generated_at": "2026-08-15T00:00:00+00:00",
            "total_users": 3,
            "catalog_size": 948,
            "owned_amiibo_count": 2,
            "most_collected": [
                {"id": "a-b", "name": "Mario", "users": 3, "pct": 100.0}
            ],
            "rarest_owned": [],
            "most_favorited": [],
            "owned_by_nobody": {"count": 946, "sample": []},
            "_top": top,
        },
    )


# ---------------------------------------------------------------------------
# Token derivation
# ---------------------------------------------------------------------------


def test_token_is_derived_from_the_secret_key():
    with override_settings(SECRET_KEY="key-one"):
        first = amiibo_report.api_token()
    with override_settings(SECRET_KEY="key-two"):
        second = amiibo_report.api_token()

    assert first and second and first != second
    # Derived, not the key itself — the token must never leak the secret.
    assert "key-one" not in first


def test_explicit_token_env_var_wins(monkeypatch):
    monkeypatch.setenv("AMIIBO_STATS_TOKEN", "my-own-token")

    assert amiibo_report.api_token() == "my-own-token"


def test_no_token_when_secret_key_is_the_unsafe_default():
    with override_settings(SECRET_KEY="unsafe-default-key"):
        assert amiibo_report.api_token() is None


def test_validation_fails_closed_without_a_configured_token():
    with override_settings(SECRET_KEY="unsafe-default-key"):
        # No configured token must mean "nobody gets in", not "everybody does".
        assert amiibo_report.token_is_valid("anything") is False
        assert amiibo_report.token_is_valid(None) is False


def test_validation_rejects_wrong_and_empty_tokens(token):
    assert amiibo_report.token_is_valid(token) is True
    assert amiibo_report.token_is_valid(token + "x") is False
    assert amiibo_report.token_is_valid("") is False
    assert amiibo_report.token_is_valid(None) is False


# ---------------------------------------------------------------------------
# Endpoint access control
# ---------------------------------------------------------------------------


def test_endpoint_rejects_missing_token(fake_report):
    response = Client().get(ENDPOINT)

    assert response.status_code == 403
    assert b"Mario" not in response.content


def test_endpoint_rejects_wrong_token(fake_report):
    response = Client().get(ENDPOINT, {"token": "not-the-token"})

    assert response.status_code == 403
    assert b"Mario" not in response.content


def test_endpoint_accepts_token_via_header(token, fake_report):
    response = Client().get(ENDPOINT, headers={"x-stats-token": token})

    assert response.status_code == 200
    assert response.json()["total_users"] == 3


def test_endpoint_accepts_token_via_query_param(token, fake_report):
    response = Client().get(ENDPOINT, {"token": token})

    assert response.status_code == 200
    assert response.json()["most_collected"][0]["name"] == "Mario"


def test_top_is_clamped_to_a_sane_range(token, fake_report):
    def top_for(value):
        return Client().get(ENDPOINT, {"token": token, "top": value}).json()["_top"]

    assert top_for("9999") == 200
    assert top_for("0") == 1
    assert top_for("junk") == 10


def test_lookup_returns_404_for_an_unknown_amiibo(token, monkeypatch):
    monkeypatch.setattr(amiibo_report, "lookup", lambda needle, limit=20: [])

    response = Client().get(ENDPOINT, {"token": token, "amiibo": "Nope"})

    assert response.status_code == 404


def test_lookup_returns_matches(token, monkeypatch):
    monkeypatch.setattr(
        amiibo_report,
        "lookup",
        lambda needle, limit=20: [
            {
                "id": "a-b",
                "name": "Mario",
                "users": 2,
                "pct": 66.7,
                "favorited_by": 1,
                "missing_from": 1,
                "total_users": 3,
            }
        ],
    )

    payload = Client().get(ENDPOINT, {"token": token, "amiibo": "Mario"}).json()

    assert payload["matches"][0]["missing_from"] == 1


def test_csv_format_returns_a_csv_attachment(token, monkeypatch):
    monkeypatch.setattr(
        amiibo_report,
        "full_table",
        lambda: [
            {
                "amiibo_id": "a-b",
                "name": "Mario",
                "collected_by": 2,
                "favorited_by": 1,
                "missing_from": 1,
                "collected_pct": 66.7,
            }
        ],
    )

    response = Client().get(ENDPOINT, {"token": token, "format": "csv"})

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    body = response.content.decode()
    assert body.splitlines()[0].startswith("amiibo_id,name,collected_by")
    assert "Mario" in body


# ---------------------------------------------------------------------------
# Owner sessions
# ---------------------------------------------------------------------------


OWNER = "owner@example.com"


def _logged_in_as(email):
    """A client carrying the session key the OAuth login flow sets.

    The project uses the signed_cookies session backend, so there is no store
    to save into — the cookie has to be attached to the client by hand.
    """
    client = Client()
    session = client.session
    session["user_email"] = email
    session.save()
    client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


@pytest.fixture
def owner_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", OWNER)


def test_owner_session_is_allowed_without_a_token(owner_configured, fake_report):
    response = _logged_in_as(OWNER).get(ENDPOINT)

    assert response.status_code == 200
    assert response.json()["total_users"] == 3


def test_owner_match_ignores_case_and_whitespace(owner_configured, fake_report):
    response = _logged_in_as("  OWNER@Example.COM  ").get(ENDPOINT)

    assert response.status_code == 200


def test_logged_in_non_owner_is_still_refused(owner_configured, fake_report):
    # The whole point: signing in to goozamiibo.com must not grant access.
    response = _logged_in_as("someone-else@example.com").get(ENDPOINT)

    assert response.status_code == 403
    assert b"Mario" not in response.content


def test_anonymous_session_is_refused(owner_configured, fake_report):
    assert Client().get(ENDPOINT).status_code == 403


def test_owner_gate_fails_closed_when_unconfigured(monkeypatch, fake_report):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(amiibo_report, "owner_emails", lambda: set())

    assert _logged_in_as(OWNER).get(ENDPOINT).status_code == 403


def test_admin_emails_accepts_a_list(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "a@x.com, B@X.com ")

    assert amiibo_report.owner_emails() == {"a@x.com", "b@x.com"}


# ---------------------------------------------------------------------------
# Firestore-backed allowlist
# ---------------------------------------------------------------------------


def test_owner_list_comes_from_firestore(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(
        firestore_client,
        "get_owner_emails",
        lambda: {"codingsina@gmail.com", "wintersina@gmail.com"},
    )
    amiibo_report.clear_owner_cache()

    assert amiibo_report.owner_emails() == {
        "codingsina@gmail.com",
        "wintersina@gmail.com",
    }


def test_both_configured_owners_get_in(monkeypatch, fake_report):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(
        firestore_client,
        "get_owner_emails",
        lambda: {"codingsina@gmail.com", "wintersina@gmail.com"},
    )
    amiibo_report.clear_owner_cache()

    assert _logged_in_as("codingsina@gmail.com").get(ENDPOINT).status_code == 200
    assert _logged_in_as("wintersina@gmail.com").get(ENDPOINT).status_code == 200
    assert _logged_in_as("someone@else.com").get(ENDPOINT).status_code == 403


def test_falls_back_to_report_recipient_when_doc_is_missing(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(firestore_client, "get_owner_emails", lambda: set())
    amiibo_report.clear_owner_cache()

    with override_settings(DAILY_REPORT_TO_EMAIL="me@example.com"):
        # A missing config document must not lock the operator out entirely.
        assert amiibo_report.owner_emails() == {"me@example.com"}


def test_firestore_failure_does_not_open_access(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)

    def boom():
        raise RuntimeError("firestore down")

    monkeypatch.setattr(firestore_client, "get_owner_emails", boom)
    amiibo_report.clear_owner_cache()

    with override_settings(DAILY_REPORT_TO_EMAIL=""):
        # Fails closed: an outage must never mean "let everyone in".
        assert amiibo_report.owner_emails() == set()


def test_owner_list_is_cached_then_released(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    calls = []

    def counted():
        calls.append(1)
        return {"a@x.com"}

    monkeypatch.setattr(firestore_client, "get_owner_emails", counted)
    amiibo_report.clear_owner_cache()

    amiibo_report.owner_emails()
    amiibo_report.owner_emails()
    assert len(calls) == 1  # second read served from cache

    amiibo_report.clear_owner_cache()
    amiibo_report.owner_emails()
    assert len(calls) == 2  # revoking someone takes effect after a clear


class _FakeOwnersDoc:
    """Minimal stand-in for the app_config/owners document."""

    def __init__(self, store):
        self._store = store

    @property
    def exists(self):
        return "data" in self._store

    def to_dict(self):
        return self._store.get("data")

    def get(self):
        return self

    def set(self, fields):
        self._store["data"] = dict(fields)


def _fake_owners_client(monkeypatch, store):
    class Client:
        def collection(self, name):
            assert name == firestore_client.APP_CONFIG_COLLECTION
            return self

        def document(self, doc_id):
            assert doc_id == firestore_client.OWNERS_DOC_ID
            return _FakeOwnersDoc(store)

    monkeypatch.setattr(firestore_client, "get_client", lambda: Client())


def test_set_owner_emails_normalizes_and_round_trips(monkeypatch):
    store = {}
    _fake_owners_client(monkeypatch, store)

    stored = firestore_client.set_owner_emails([" A@X.com ", "b@x.com", "", "a@x.com"])

    assert stored == {"a@x.com", "b@x.com"}
    assert store["data"]["emails"] == ["a@x.com", "b@x.com"]
    assert firestore_client.get_owner_emails() == {"a@x.com", "b@x.com"}


def test_get_owner_emails_is_empty_when_doc_missing(monkeypatch):
    _fake_owners_client(monkeypatch, {})

    assert firestore_client.get_owner_emails() == set()


def test_get_owner_emails_tolerates_a_console_typed_string(monkeypatch):
    # Someone editing the doc by hand in the Firestore console may type a
    # comma-separated string instead of an array.
    _fake_owners_client(monkeypatch, {"data": {"emails": "A@x.com, b@x.com"}})

    assert firestore_client.get_owner_emails() == {"a@x.com", "b@x.com"}


def test_token_still_works_alongside_the_session_gate(
    owner_configured, token, fake_report
):
    # Automation (make amiibo-stats-remote, curl) has no session and must not
    # be locked out by adding the owner path.
    response = Client().get(ENDPOINT, headers={"x-stats-token": token})

    assert response.status_code == 200


def test_url_is_wired_under_the_expected_name(token, fake_report):
    assert reverse("amiibo_stats_api") == ENDPOINT
    response = Client().get(reverse("amiibo_stats_api"), {"token": token})
    assert response.status_code == 200
