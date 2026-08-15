"""Tests for the tracked-amiibo JSON blob on each user_interactions document.

The blob mirrors a user's Google Sheet (collected + favorited) so catalog-wide
questions can be answered without touching anyone's sheet.
"""

import json

import pytest

from tracker import amiibo_report, collection_snapshot, firestore_client


MARIO = {
    "head": "01000000",
    "tail": "00000002",
    "gameSeries": "Super Mario",
    "name": "Mario",
}
LUIGI = {
    "head": "01010000",
    "tail": "00040002",
    "gameSeries": "Super Mario",
    "name": "Luigi",
}
PEACH = {
    "head": "01020000",
    "tail": "00050002",
    "gameSeries": "Super Mario",
    "name": "Peach",
}
CATALOG = [MARIO, LUIGI, PEACH]


# ---------------------------------------------------------------------------
# Fakes
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

    def set(self, fields, merge=False):
        if merge and self.id in self._store:
            self._store[self.id].update(fields)
        else:
            self._store[self.id] = dict(fields)


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return FakeDocRef(self._store, doc_id)

    def stream(self):
        return iter(FakeSnapshot(k, v) for k, v in self._store.items())


class FakeTransaction:
    def __init__(self, store):
        self._store = store

    def set(self, ref, fields, merge=False):
        ref.set(fields, merge=merge)


class FakeClient:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return FakeCollection(self.store)

    def transaction(self):
        return FakeTransaction(self.store)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(firestore_client, "get_client", lambda: client)
    monkeypatch.setattr(
        firestore_client,
        "_apply_amiibo_entry_txn",
        firestore_client._apply_amiibo_entry,
    )
    return client


@pytest.fixture
def tracking_on(monkeypatch):
    monkeypatch.setenv("USER_INTERACTION_TRACKING_ENABLED", "true")


@pytest.fixture
def local_catalog(monkeypatch):
    monkeypatch.setattr(
        collection_snapshot._Catalog, "_fetch_local_amiibos", lambda self: CATALOG
    )


def _stored_entries(client, user_hash):
    return firestore_client.decode_amiibos(client.store[user_hash]["amiibos"])


# ---------------------------------------------------------------------------
# Building entries from the sheet
# ---------------------------------------------------------------------------


def test_build_entries_keeps_only_tracked_amiibos():
    collected = {collection_snapshot.sheet_id(MARIO): "1"}
    favorites = {collection_snapshot.sheet_id(LUIGI): "1"}

    entries = collection_snapshot.build_entries(CATALOG, collected, favorites)

    # Peach is neither collected nor favorited, so she is not stored at all.
    assert [e["name"] for e in entries] == ["Mario", "Luigi"]
    assert entries[0] == {
        "id": "01000000-00000002",
        "name": "Mario",
        "collected": True,
        "favorite": False,
    }
    assert entries[1]["favorite"] is True
    assert entries[1]["collected"] is False


def test_entries_use_stable_head_tail_ids_not_the_sheet_key():
    entries = collection_snapshot.build_entries(
        CATALOG, {collection_snapshot.sheet_id(MARIO): "1"}, {}
    )

    # The sheet keys rows by head+gameSeries+tail; the blob must not, so the
    # data survives a game series being renamed.
    assert entries[0]["id"] == "01000000-00000002"
    assert collection_snapshot.sheet_id(MARIO) == "01000000Super Mario00000002"


# ---------------------------------------------------------------------------
# Snapshot + incremental writes
# ---------------------------------------------------------------------------


def test_login_snapshot_stores_blob_and_counts(fake_client, tracking_on):
    collected = {
        collection_snapshot.sheet_id(MARIO): "1",
        collection_snapshot.sheet_id(LUIGI): "1",
    }
    favorites = {collection_snapshot.sheet_id(MARIO): "1"}

    collection_snapshot.record_login_snapshot("hash-a", CATALOG, collected, favorites)

    doc = fake_client.store["hash-a"]
    assert doc["amiibo_count"] == 2
    assert doc["favorite_count"] == 1
    assert isinstance(doc["amiibos"], str)  # stored as a JSON string, not an array
    assert {e["name"] for e in _stored_entries(fake_client, "hash-a")} == {
        "Mario",
        "Luigi",
    }


def test_snapshot_replaces_stale_entries(fake_client, tracking_on):
    collection_snapshot.record_login_snapshot(
        "hash-a", CATALOG, {collection_snapshot.sheet_id(MARIO): "1"}, {}
    )
    # User later uncollected Mario and collected Luigi in their sheet.
    collection_snapshot.record_login_snapshot(
        "hash-a", CATALOG, {collection_snapshot.sheet_id(LUIGI): "1"}, {}
    )

    assert [e["name"] for e in _stored_entries(fake_client, "hash-a")] == ["Luigi"]
    assert fake_client.store["hash-a"]["amiibo_count"] == 1


def test_snapshot_preserves_interaction_counters(fake_client, tracking_on):
    fake_client.store["hash-a"] = {"interactions": 12, "first_seen": "earlier"}

    collection_snapshot.record_login_snapshot(
        "hash-a", CATALOG, {collection_snapshot.sheet_id(MARIO): "1"}, {}
    )

    doc = fake_client.store["hash-a"]
    assert doc["interactions"] == 12
    assert doc["first_seen"] == "earlier"
    assert doc["amiibo_count"] == 1


def test_toggle_adds_then_removes_an_entry(fake_client, tracking_on, local_catalog):
    user_hash = "hash-a"
    mario_sheet_id = collection_snapshot.sheet_id(MARIO)

    collection_snapshot.record_toggle(user_hash, mario_sheet_id, collected=True)
    assert [e["name"] for e in _stored_entries(fake_client, user_hash)] == ["Mario"]

    collection_snapshot.record_toggle(user_hash, mario_sheet_id, collected=False)
    # No longer collected or favorited, so the entry is dropped entirely.
    assert _stored_entries(fake_client, user_hash) == []
    assert fake_client.store[user_hash]["amiibo_count"] == 0


def test_toggle_favorite_keeps_collected_flag(fake_client, tracking_on, local_catalog):
    sheet_id = collection_snapshot.sheet_id(MARIO)

    collection_snapshot.record_toggle("hash-a", sheet_id, collected=True)
    collection_snapshot.record_toggle("hash-a", sheet_id, favorite=True)

    entry = _stored_entries(fake_client, "hash-a")[0]
    assert entry["collected"] is True
    assert entry["favorite"] is True


def test_toggle_ignores_unknown_amiibo_ids(fake_client, tracking_on, local_catalog):
    collection_snapshot.record_toggle("hash-a", "not-a-real-id", collected=True)

    # An unjoinable row would poison the stats, so nothing is written.
    assert fake_client.store == {}


def test_writes_are_skipped_when_tracking_disabled(fake_client, monkeypatch):
    monkeypatch.delenv("USER_INTERACTION_TRACKING_ENABLED", raising=False)
    monkeypatch.setenv("ENV_NAME", "development")

    collection_snapshot.record_login_snapshot(
        "hash-a", CATALOG, {collection_snapshot.sheet_id(MARIO): "1"}, {}
    )
    collection_snapshot.record_toggle("hash-a", "x", collected=True)

    assert fake_client.store == {}


def test_snapshot_failure_never_propagates(monkeypatch, tracking_on):
    def boom(*_args, **_kwargs):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(firestore_client, "save_amiibo_snapshot", boom)

    # Must not raise — a failed snapshot cannot break login.
    collection_snapshot.record_login_snapshot("hash-a", CATALOG, {}, {})


# ---------------------------------------------------------------------------
# decode_amiibos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["", None, "not json", "{}", '"a string"', 42, "[1, 2, 3]"]
)
def test_decode_tolerates_junk(raw):
    # One corrupt document must never take down a report that scans every user.
    assert firestore_client.decode_amiibos(raw) == []


def test_decode_accepts_a_native_array():
    assert firestore_client.decode_amiibos([{"id": "a"}]) == [{"id": "a"}]


def test_decode_round_trips_a_snapshot(fake_client, tracking_on):
    collection_snapshot.record_login_snapshot(
        "hash-a", CATALOG, {collection_snapshot.sheet_id(MARIO): "1"}, {}
    )
    raw = fake_client.store["hash-a"]["amiibos"]

    assert json.loads(raw) == firestore_client.decode_amiibos(raw)


# ---------------------------------------------------------------------------
# amiibo_stats tally
# ---------------------------------------------------------------------------


def _blob(*entries):
    return json.dumps(list(entries))


def test_tally_counts_holders_across_users():
    rows = [
        {
            "amiibos": _blob(
                {"id": "m", "name": "Mario", "collected": True, "favorite": True},
                {"id": "l", "name": "Luigi", "collected": True, "favorite": False},
            )
        },
        {"amiibos": _blob({"id": "m", "name": "Mario", "collected": True})},
        # A user with no blob yet must not inflate the denominator.
        {"interactions": 3},
    ]

    collected, favorited, total_users = amiibo_report.tally(rows)

    assert total_users == 2
    assert collected["m"] == 2
    assert collected["l"] == 1
    assert favorited["m"] == 1


def test_tally_ignores_uncollected_and_idless_entries():
    rows = [
        {
            "amiibos": _blob(
                {"id": "m", "collected": False, "favorite": True},
                {"name": "no id", "collected": True},
            )
        }
    ]

    collected, favorited, total_users = amiibo_report.tally(rows)

    assert total_users == 1
    assert collected["m"] == 0
    assert favorited["m"] == 1
