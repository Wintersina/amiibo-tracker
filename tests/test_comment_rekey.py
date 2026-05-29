"""Tests for migrating amiibo comments when a placeholder's id changes.

When the scraper backfills an "upcoming" placeholder amiibo with its real
Nintendo head/tail, the amiibo's comment key (``head-tail``) changes. These
tests cover the re-keying that keeps previously posted comments attached.
"""

import pytest

from tracker import firestore_client, scrapers


# ---------------------------------------------------------------------------
# Fakes for the Firestore client
# ---------------------------------------------------------------------------


class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = self

    def to_dict(self):
        return dict(self._data)


class FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter=None):  # noqa: A002 - mirrors firestore API kwarg
        return self

    def stream(self):
        return iter(self._docs)


class FakeBatch:
    def __init__(self, sink):
        self._sink = sink

    def update(self, ref, fields):
        self._sink.append((ref, fields))

    def commit(self):
        pass


class FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter=None):  # noqa: A002
        return FakeQuery(self._docs)


class FakeClient:
    def __init__(self, docs):
        self._docs = docs
        self.batched_updates = []

    def collection(self, name):
        return FakeCollection(self._docs)

    def batch(self):
        return FakeBatch(self.batched_updates)


# ---------------------------------------------------------------------------
# rekey_comments
# ---------------------------------------------------------------------------


def test_rekey_is_noop_when_ids_match(monkeypatch):
    called = []
    monkeypatch.setattr(firestore_client, "get_client", lambda: called.append(True))
    moved = firestore_client.rekey_comments(
        "amiibo_comments", "amiibo_id", "same-id", "same-id"
    )
    assert moved == 0
    # Should short-circuit before ever touching Firestore.
    assert called == []


def test_rekey_returns_zero_when_no_matches(monkeypatch):
    monkeypatch.setattr(firestore_client, "get_client", lambda: FakeClient(docs=[]))
    moved = firestore_client.rekey_comments(
        "amiibo_comments", "amiibo_id", "ffaaaaaa-ffbbbbbb", "04380001-03000502"
    )
    assert moved == 0


def test_rekey_updates_every_matching_doc(monkeypatch):
    docs = [FakeDoc("c1", {"amiibo_id": "old"}), FakeDoc("c2", {"amiibo_id": "old"})]
    client = FakeClient(docs=docs)
    monkeypatch.setattr(firestore_client, "get_client", lambda: client)

    moved = firestore_client.rekey_comments(
        "amiibo_comments", "amiibo_id", "old", "new"
    )

    assert moved == 2
    assert {ref.id for ref, _ in client.batched_updates} == {"c1", "c2"}
    assert all(fields == {"amiibo_id": "new"} for _, fields in client.batched_updates)


def test_rekey_chunks_writes_over_batch_limit(monkeypatch):
    docs = [FakeDoc(f"c{i}", {"amiibo_id": "old"}) for i in range(501)]
    client = FakeClient(docs=docs)
    monkeypatch.setattr(firestore_client, "get_client", lambda: client)

    moved = firestore_client.rekey_comments(
        "amiibo_comments", "amiibo_id", "old", "new"
    )

    assert moved == 501
    assert len(client.batched_updates) == 501


# ---------------------------------------------------------------------------
# Scraper wiring (backfill_amiibo_data -> migrate_comments_on_id_change)
# ---------------------------------------------------------------------------


def test_backfill_migrates_comments_to_real_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        scrapers,
        "rekey_comments",
        lambda collection, key_field, old, new: calls.append((old, new)) or 1,
    )

    scraper = scrapers.AmiiboLifeScraper()
    placeholder = {
        "head": "ffaaaaaa",
        "tail": "ffbbbbbb",
        "character": "Leon",
        "gameSeries": "Resident Evil",
        "amiiboSeries": "Resident Evil",
        "name": "Leon S. Kennedy",
    }
    api_amiibo = {"head": "04380001", "tail": "03000502", "name": "Leon S. Kennedy"}

    scraper.backfill_amiibo_data(placeholder, api_amiibo)

    assert calls == [("ffaaaaaa-ffbbbbbb", "04380001-03000502")]
    assert placeholder["head"] == "04380001"
    assert placeholder["tail"] == "03000502"


def test_backfill_skips_migration_when_id_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(
        scrapers,
        "rekey_comments",
        lambda collection, key_field, old, new: calls.append((old, new)) or 1,
    )

    scraper = scrapers.AmiiboLifeScraper()
    placeholder = {
        "head": "04380001",
        "tail": "03000502",
        "character": "Leon",
        "gameSeries": "Resident Evil",
        "amiiboSeries": "Resident Evil",
        "name": "Leon S. Kennedy",
    }
    api_amiibo = {"head": "04380001", "tail": "03000502", "name": "Leon S. Kennedy"}

    scraper.backfill_amiibo_data(placeholder, api_amiibo)

    # Same head/tail -> nothing to migrate.
    assert calls == []


def test_backfill_migration_failure_does_not_raise(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(scrapers, "rekey_comments", boom)

    scraper = scrapers.AmiiboLifeScraper()
    placeholder = {
        "head": "ffaaaaaa",
        "tail": "ffbbbbbb",
        "character": "Leon",
        "gameSeries": "Resident Evil",
        "amiiboSeries": "Resident Evil",
        "name": "Leon S. Kennedy",
    }
    api_amiibo = {"head": "04380001", "tail": "03000502", "name": "Leon S. Kennedy"}

    # Best-effort: a Firestore failure must not abort the scrape.
    scraper.backfill_amiibo_data(placeholder, api_amiibo)
    assert placeholder["head"] == "04380001"
