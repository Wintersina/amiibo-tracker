"""Keeps each user's tracked-amiibo blob in sync with their Google Sheet.

The sheet is the source of truth for what someone has collected or favorited.
This module mirrors it into the `amiibos` field on the user's
`user_interactions` document so catalog-wide questions ("most collected",
"rarest", "how many people have X") can be answered without touching anyone's
sheet — see `manage.py amiibo_stats`.

Two write paths, deliberately:

* `record_login_snapshot` rebuilds the whole blob from a full sheet read at
  login. This is the authoritative one — it self-heals any drift, and it is the
  only reason the data is trustworthy for "most missing" style questions, which
  would otherwise only ever see amiibos someone happened to click after this
  feature shipped.
* `record_toggle` patches a single entry when someone collects/favorites,
  keeping the blob fresh between logins.

Ids: the sheet keys rows by `head + gameSeries + tail`, which embeds a mutable
field. The blob stores `head-tail` instead — the stable NFC identifier already
used by amiibo detail URLs and the comments collection — so the data stays
correlatable if a game series is ever renamed.

Every entry point is best-effort: analytics must never break a request.
"""

import logging

from tracker import firestore_client
from tracker.helpers import AmiiboLocalFetchMixin
from tracker.observability import interaction_tracking_enabled


logger = logging.getLogger(__name__)


class _Catalog(AmiiboLocalFetchMixin):
    """Reuses the mixin's cache-backed loader for the local amiibo database."""


def sheet_id(amiibo: dict) -> str:
    """The sheet's row key: head + gameSeries + tail (see AmiiboService)."""
    return f"{amiibo.get('head', '')}{amiibo.get('gameSeries', '')}{amiibo.get('tail', '')}"


def stable_id(amiibo: dict) -> str:
    """The durable identifier stored in the blob: head-tail."""
    return f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"


def catalog_index() -> dict:
    """Map each sheet row key to the {id, name} the blob stores."""
    index = {}
    for amiibo in _Catalog()._fetch_local_amiibos():
        index[sheet_id(amiibo)] = {
            "id": stable_id(amiibo),
            "name": amiibo.get("name", ""),
        }
    return index


def build_entries(amiibos, collected_map, favorite_map) -> list[dict]:
    """Turn a catalog + the sheet's two status columns into blob entries.

    Only amiibos the user actually tracks are kept; storing ~950 all-false rows
    per user would bloat every document for no gain.
    """
    entries = []
    for amiibo in amiibos:
        key = sheet_id(amiibo)
        collected = str(collected_map.get(key, "0")) == "1"
        favorite = str(favorite_map.get(key, "0")) == "1"
        if not (collected or favorite):
            continue
        entries.append(
            {
                "id": stable_id(amiibo),
                "name": amiibo.get("name", ""),
                "collected": collected,
                "favorite": favorite,
            }
        )
    return entries


def record_login_snapshot(user_hash, amiibos, collected_map, favorite_map) -> None:
    """Rebuild the user's blob from a full sheet read. Best-effort."""
    if not user_hash or not interaction_tracking_enabled():
        return
    try:
        entries = build_entries(amiibos, collected_map, favorite_map)
        firestore_client.save_amiibo_snapshot(user_hash, entries)
    except Exception:
        logger.debug("amiibo-snapshot-failed", exc_info=True)


def record_toggle(user_hash, sheet_amiibo_id, *, collected=None, favorite=None) -> None:
    """Patch one amiibo in the user's blob after a toggle. Best-effort."""
    if not user_hash or not sheet_amiibo_id or not interaction_tracking_enabled():
        return
    try:
        known = catalog_index().get(sheet_amiibo_id)
        if known is None:
            # An id we cannot resolve would poison the stats with a row nothing
            # can be joined against; drop it and let the next login snapshot
            # reconcile.
            logger.debug("amiibo-toggle-unknown-id | id=%s", sheet_amiibo_id)
            return
        firestore_client.update_amiibo_entry(
            user_hash,
            known["id"],
            known["name"],
            collected=collected,
            favorite=favorite,
        )
    except Exception:
        logger.debug("amiibo-toggle-record-failed", exc_info=True)
