"""Tests for the persistent per-user interaction counter and the daily report.

Authenticated user-actions increment a row in the Firestore `user_interactions`
collection; the daily report derives new/active/total counts from that table
instead of querying Loki.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tracker import firestore_client, observability
from tracker.management.commands.report_daily_users import Command


# ---------------------------------------------------------------------------
# Fakes for the Firestore client
# ---------------------------------------------------------------------------


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, store, doc_id):
        self._store = store
        self.id = doc_id

    def get(self, transaction=None):
        return FakeSnapshot(self.id, self._store.get(self.id))


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return FakeDocRef(self._store, doc_id)

    def stream(self):
        return iter(FakeSnapshot(doc_id, data) for doc_id, data in self._store.items())


class FakeTransaction:
    """Applies writes straight through; enough to exercise our transaction body."""

    def __init__(self, store):
        self._store = store

    def set(self, ref, fields):
        self._store[ref.id] = dict(fields)

    def update(self, ref, fields):
        current = self._store[ref.id]
        for key, value in fields.items():
            # Mirror firestore.Increment semantics for the counter field.
            if hasattr(value, "value"):
                current[key] = current.get(key, 0) + value.value
            else:
                current[key] = value


class FakeClient:
    def __init__(self, store=None):
        self.store = store if store is not None else {}

    def collection(self, name):
        return FakeCollection(self.store)

    def transaction(self):
        return FakeTransaction(self.store)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(firestore_client, "get_client", lambda: client)
    # The real decorator drives a commit/retry loop against a live backend;
    # swap in the plain body so the fake transaction is what gets exercised.
    monkeypatch.setattr(
        firestore_client, "_apply_interaction_txn", firestore_client._apply_interaction
    )
    return client


# ---------------------------------------------------------------------------
# record_interaction
# ---------------------------------------------------------------------------


def test_first_interaction_creates_row(fake_client):
    is_new = firestore_client.record_interaction("hash-a")

    assert is_new is True
    row = fake_client.store["hash-a"]
    assert row["interactions"] == 1
    assert row["first_seen"] == row["last_seen"]


def test_repeat_interactions_upsert_the_same_row(fake_client):
    """Repeat activity updates one row in place — it never appends new ones."""
    firestore_client.record_interaction("hash-a")
    original_first_seen = fake_client.store["hash-a"]["first_seen"]

    assert firestore_client.record_interaction("hash-a") is False
    assert firestore_client.record_interaction("hash-a") is False

    # Three interactions, still exactly one document.
    assert list(fake_client.store) == ["hash-a"]
    row = fake_client.store["hash-a"]
    assert row["interactions"] == 3
    assert row["first_seen"] == original_first_seen
    assert row["last_seen"] >= original_first_seen


def test_distinct_users_get_distinct_rows(fake_client):
    firestore_client.record_interaction("hash-a")
    firestore_client.record_interaction("hash-b")
    firestore_client.record_interaction("hash-a")

    assert sorted(fake_client.store) == ["hash-a", "hash-b"]
    assert fake_client.store["hash-a"]["interactions"] == 2
    assert fake_client.store["hash-b"]["interactions"] == 1


def test_blank_hash_is_ignored(fake_client):
    assert firestore_client.record_interaction("") is False
    assert firestore_client.record_interaction(None) is False
    assert fake_client.store == {}


# ---------------------------------------------------------------------------
# The observability hook
# ---------------------------------------------------------------------------


def test_tracking_defaults_off_outside_production(monkeypatch):
    monkeypatch.delenv("USER_INTERACTION_TRACKING_ENABLED", raising=False)
    monkeypatch.setenv("ENV_NAME", "development")

    assert observability.interaction_tracking_enabled() is False


def test_tracking_defaults_on_in_production(monkeypatch):
    # Shipping needs no infra change: ENV_NAME is already set on Cloud Run.
    monkeypatch.delenv("USER_INTERACTION_TRACKING_ENABLED", raising=False)
    monkeypatch.setenv("ENV_NAME", "production")

    assert observability.interaction_tracking_enabled() is True


def test_env_override_wins_in_both_directions(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "development")
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "true")
    assert observability.interaction_tracking_enabled() is True

    monkeypatch.setenv("ENV_NAME", "production")
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "false")
    assert observability.interaction_tracking_enabled() is False


def test_hook_is_noop_when_tracking_disabled(monkeypatch):
    monkeypatch.delenv("USER_INTERACTION_TRACKING_ENABLED", raising=False)
    monkeypatch.setenv("ENV_NAME", "development")
    called = []
    monkeypatch.setattr(
        firestore_client, "record_interaction", lambda h: called.append(h)
    )

    observability.record_interaction("hash-a")

    assert called == []


def test_hook_records_when_enabled(monkeypatch):
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "true")
    called = []
    monkeypatch.setattr(
        firestore_client, "record_interaction", lambda h: called.append(h)
    )

    observability.record_interaction("hash-a")

    assert called == ["hash-a"]


def test_hook_swallows_firestore_failures(monkeypatch):
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "true")

    def boom(_hash):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(firestore_client, "record_interaction", boom)

    # Must not propagate — observability never breaks a request.
    observability.record_interaction("hash-a")


def test_anonymous_users_are_never_recorded(monkeypatch):
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "true")
    called = []
    monkeypatch.setattr(
        firestore_client, "record_interaction", lambda h: called.append(h)
    )

    # hash_email(None) is what an anonymous request produces.
    observability.record_interaction(observability.hash_email(None))

    assert called == []


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


REPORT_DATE = datetime(2026, 8, 12, tzinfo=timezone.utc).date()


def _row(user_hash, interactions, first_seen, last_seen):
    return {
        "user_hash": user_hash,
        "interactions": interactions,
        "first_seen": first_seen,
        "last_seen": last_seen,
    }


def test_summarise_splits_new_active_and_total():
    day = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    earlier = day - timedelta(days=30)

    rows = [
        # New on the report date, and active on it.
        _row("new-and-active", 2, day, day),
        # Existing user, active on the report date.
        _row("returning", 40, earlier, day),
        # Existing user, dormant.
        _row("dormant", 7, earlier, earlier),
    ]

    stats = Command()._summarise(rows, REPORT_DATE)

    assert [r["user_hash"] for r in stats["new_users"]] == ["new-and-active"]
    assert stats["active"] == 2
    assert stats["total"] == 3


def test_summarise_excludes_users_created_after_the_report_date():
    day = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    later = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

    rows = [
        _row("on-the-day", 1, day, day),
        _row("signed-up-later", 5, later, later),
    ]

    stats = Command()._summarise(rows, REPORT_DATE)

    # A backfilled --date reports the totals as they stood then.
    assert stats["total"] == 1
    assert [r["user_hash"] for r in stats["new_users"]] == ["on-the-day"]


def test_summarise_skips_rows_without_first_seen():
    rows = [_row("broken", 3, None, None)]

    stats = Command()._summarise(rows, REPORT_DATE)

    assert stats["total"] == 0
    assert stats["new_users"] == []


def test_summarise_treats_naive_timestamps_as_utc():
    naive = datetime(2026, 8, 12, 10, 0)

    stats = Command()._summarise([_row("naive", 1, naive, naive)], REPORT_DATE)

    assert stats["total"] == 1
    assert len(stats["new_users"]) == 1


def test_csv_has_one_row_per_user_with_is_new_flag():
    day = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    earlier = day - timedelta(days=30)
    known = [
        _row("aaa", 2, day, day),
        _row("bbb", 40, earlier, day),
    ]

    text = Command()._render_csv(known, REPORT_DATE).decode("utf-8")
    lines = text.strip().splitlines()

    assert lines[0] == "user_hash,total_interactions,first_seen,last_seen,is_new"
    assert len(lines) == 3
    assert lines[1].startswith("aaa,2,")
    assert lines[1].endswith(",true")
    assert lines[2].startswith("bbb,40,")
    assert lines[2].endswith(",false")


def test_html_reports_the_headline_numbers():
    day = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    stats = Command()._summarise(
        [
            _row("aaa", 2, day, day),
            _row("bbb", 40, day - timedelta(days=30), day),
        ],
        REPORT_DATE,
    )

    html = Command()._render_html(REPORT_DATE, stats)

    assert "<strong>1</strong> new user(s)" in html
    assert "<strong>2</strong> total unique user(s)" in html
    assert "<strong>2</strong> active" in html


# ---------------------------------------------------------------------------
# list_user_interactions
# ---------------------------------------------------------------------------


def test_list_user_interactions_sorts_by_last_seen_desc(fake_client):
    day = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    fake_client.store.update(
        {
            "old": {"interactions": 1, "first_seen": day, "last_seen": day},
            "recent": {
                "interactions": 1,
                "first_seen": day,
                "last_seen": day + timedelta(days=1),
            },
            "no-last-seen": {"interactions": 1, "first_seen": day},
        }
    )

    rows = firestore_client.list_user_interactions()

    assert [r["user_hash"] for r in rows] == ["recent", "old", "no-last-seen"]
