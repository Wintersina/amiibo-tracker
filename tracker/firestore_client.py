import json
import os
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

AMIIBO_COMMENTS_COLLECTION = "amiibo_comments"
BLOG_COMMENTS_COLLECTION = "blog_comments"
USER_INTERACTIONS_COLLECTION = "user_interactions"
APP_CONFIG_COLLECTION = "app_config"
OWNERS_DOC_ID = "owners"


@lru_cache(maxsize=1)
def get_client() -> firestore.Client:
    project = os.environ.get("GCP_PROJECT_ID")
    return firestore.Client(project=project) if project else firestore.Client()


def list_comments(
    collection: str, key_field: str, key_value: str, limit: int = 50
) -> list[dict]:
    docs = (
        get_client()
        .collection(collection)
        .where(filter=firestore.FieldFilter(key_field, "==", key_value))
        .where(filter=firestore.FieldFilter("is_hidden", "==", False))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


def add_comment(
    collection: str,
    key_field: str,
    key_value: str,
    user_email: str,
    display_name: str,
    body: str,
    parent_id: str | None = None,
) -> str:
    _, doc_ref = (
        get_client()
        .collection(collection)
        .add(
            {
                key_field: key_value,
                "user_email": user_email,
                "display_name": display_name,
                "body": body,
                "parent_id": parent_id,
                "created_at": firestore.SERVER_TIMESTAMP,
                "is_hidden": False,
            }
        )
    )
    return doc_ref.id


def get_comment(collection: str, doc_id: str) -> dict | None:
    """Return a single comment by document id, or ``None`` if it doesn't exist."""
    doc = get_client().collection(collection).document(doc_id).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}


def delete_comment(collection: str, doc_id: str, user_email: str) -> bool:
    """Delete a comment only if ``user_email`` is its author.

    Returns ``True`` on a successful delete, ``False`` if the comment is missing
    or owned by someone else. Replies to a deleted parent are intentionally left
    in place — the listing renders the orphaned thread under a "removed"
    placeholder so the conversation stays readable.
    """
    ref = get_client().collection(collection).document(doc_id)
    doc = ref.get()
    if not doc.exists or doc.to_dict().get("user_email") != user_email:
        return False
    ref.delete()
    return True


def rekey_comments(
    collection: str, key_field: str, old_value: str, new_value: str
) -> int:
    """
    Re-point every comment keyed by ``old_value`` to ``new_value``.

    Used when an amiibo's identity (head-tail) changes — e.g. a scraped
    "upcoming" placeholder is backfilled with its real Nintendo IDs — so that
    comments posted against the placeholder are not orphaned. Hidden/moderated
    comments are migrated too (no ``is_hidden`` filter). Returns the number of
    comments re-keyed.
    """
    if old_value == new_value:
        return 0

    client = get_client()
    docs = list(
        client.collection(collection)
        .where(filter=firestore.FieldFilter(key_field, "==", old_value))
        .stream()
    )
    if not docs:
        return 0

    migrated = 0
    # Firestore caps a batch at 500 writes; chunk to stay under the limit.
    for start in range(0, len(docs), 500):
        chunk = docs[start : start + 500]
        batch = client.batch()
        for doc in chunk:
            batch.update(doc.reference, {key_field: new_value})
        batch.commit()
        migrated += len(chunk)

    return migrated


# ---------------------------------------------------------------------------
# User interactions
# ---------------------------------------------------------------------------
#
# One document per user, keyed by the same opaque `user_hash` the log pipeline
# uses (sha256 of the salted, lowercased email — see observability.hash_email).
# No raw email ever reaches this collection. The document is deliberately tiny:
#
#     interactions  int         total user-actions ever recorded
#     first_seen    timestamp   when the user was first recorded (UTC)
#     last_seen     timestamp   most recent recorded action (UTC)
#
# That is enough for the daily report to derive "new users on date D"
# (first_seen falls on D), "active on D" (last_seen falls on D), and "total
# unique users so far" (document count), without storing any per-event rows.
#
# The same document also carries the user's tracked amiibos, for catalog-wide
# questions ("most collected", "rarest", "how many people have X"):
#
#     amiibos          str         JSON list of {id, name, collected, favorite}
#     amiibo_count     int         how many entries are collected
#     favorite_count   int         how many entries are favorited
#     amiibos_synced_at timestamp  when the blob was last rebuilt from the sheet
#
# `amiibos` is a JSON *string* rather than a native Firestore array on purpose:
# Firestore auto-indexes every element of an array field, so a ~950-entry list
# of maps would write thousands of index entries per save. Every question we
# want to ask is a cross-user aggregate that scans all documents anyway, so the
# index buys nothing. Only collected-or-favorited amiibos are stored; the rest
# of the catalog is implied by the local amiibo database.


def _apply_interaction(transaction, ref, now):
    """Create-or-increment a user row inside a transaction. Returns is_new."""
    snapshot = ref.get(transaction=transaction)
    if snapshot.exists:
        transaction.update(
            ref,
            {"interactions": firestore.Increment(1), "last_seen": now},
        )
        return False
    transaction.set(ref, {"interactions": 1, "first_seen": now, "last_seen": now})
    return True


# Kept separate from the body above so the transaction logic stays a plain,
# directly-callable function under test.
_apply_interaction_txn = firestore.transactional(_apply_interaction)


def record_interaction(user_hash: str) -> bool:
    """Count one interaction for ``user_hash``, creating the row on first sight.

    Returns ``True`` when this call created the user's row (i.e. a genuinely new
    user), ``False`` when it incremented an existing one. A transaction is used
    rather than a bare merge-set because ``first_seen`` must survive every
    subsequent write, and concurrent requests from the same user would otherwise
    race on the counter.
    """
    if not user_hash:
        return False
    client = get_client()
    ref = client.collection(USER_INTERACTIONS_COLLECTION).document(user_hash)
    return _apply_interaction_txn(client.transaction(), ref, datetime.now(timezone.utc))


def list_user_interactions() -> list[dict]:
    """Return every user row, newest-active first.

    The whole collection is streamed because the daily report renders one CSV
    line per user and needs the full set anyway; at this app's scale that is a
    handful of reads per day.
    """
    docs = get_client().collection(USER_INTERACTIONS_COLLECTION).stream()
    rows = [{"user_hash": d.id, **(d.to_dict() or {})} for d in docs]
    # A row written by an older/partial code path may lack last_seen; sort those
    # last rather than letting the comparison blow up on None.
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    rows.sort(key=lambda r: r.get("last_seen") or epoch, reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Tracked amiibos (the `amiibos` JSON blob on each user document)
# ---------------------------------------------------------------------------


def decode_amiibos(raw) -> list[dict]:
    """Parse a stored `amiibos` blob into a list, tolerating junk.

    Returns ``[]`` for anything unreadable so one corrupt document can never
    take down a report that scans every user.
    """
    if isinstance(raw, list):  # tolerate a doc written as a native array
        return [entry for entry in raw if isinstance(entry, dict)]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, dict)]


def _encode_amiibos(entries) -> str:
    return json.dumps(entries, separators=(",", ":"), sort_keys=True)


def _amiibo_fields(entries) -> dict:
    entries = sorted(entries, key=lambda e: e.get("id") or "")
    return {
        "amiibos": _encode_amiibos(entries),
        "amiibo_count": sum(1 for e in entries if e.get("collected")),
        "favorite_count": sum(1 for e in entries if e.get("favorite")),
        "amiibos_synced_at": datetime.now(timezone.utc),
    }


def save_amiibo_snapshot(user_hash: str, entries: list[dict]) -> int:
    """Replace a user's amiibo blob wholesale from an authoritative read.

    Used at login, where the user's Google Sheet has just been read in full.
    A merge-set is safe here (no read needed) because the blob is being
    replaced outright and the interaction counters live in separate fields.
    Returns the number of entries stored.
    """
    if not user_hash:
        return 0
    ref = get_client().collection(USER_INTERACTIONS_COLLECTION).document(user_hash)
    ref.set(_amiibo_fields(entries), merge=True)
    return len(entries)


def _apply_amiibo_entry(transaction, ref, amiibo_id, name, collected, favorite):
    """Patch one amiibo inside the blob, leaving the others untouched."""
    snapshot = ref.get(transaction=transaction)
    entries = decode_amiibos((snapshot.to_dict() or {}).get("amiibos"))

    existing = next((e for e in entries if e.get("id") == amiibo_id), None)
    if existing is None:
        existing = {
            "id": amiibo_id,
            "name": name,
            "collected": False,
            "favorite": False,
        }
        entries.append(existing)
    if name:
        existing["name"] = name
    if collected is not None:
        existing["collected"] = collected
    if favorite is not None:
        existing["favorite"] = favorite

    # Drop entries the user no longer tracks at all, so the blob stays a record
    # of what someone has rather than everything they ever clicked.
    entries = [e for e in entries if e.get("collected") or e.get("favorite")]
    transaction.set(ref, _amiibo_fields(entries), merge=True)


_apply_amiibo_entry_txn = firestore.transactional(_apply_amiibo_entry)


def update_amiibo_entry(
    user_hash: str,
    amiibo_id: str,
    name: str = "",
    *,
    collected: bool | None = None,
    favorite: bool | None = None,
) -> None:
    """Flip one amiibo's collected/favorite flag in the user's blob.

    Keeps the blob fresh between logins, when the full snapshot is rebuilt.
    Read-modify-write under a transaction so two quick toggles cannot clobber
    each other. ``None`` leaves a flag unchanged.
    """
    if not user_hash or not amiibo_id:
        return
    client = get_client()
    ref = client.collection(USER_INTERACTIONS_COLLECTION).document(user_hash)
    _apply_amiibo_entry_txn(
        client.transaction(), ref, amiibo_id, name, collected, favorite
    )


# ---------------------------------------------------------------------------
# App config: operator allowlist
# ---------------------------------------------------------------------------
#
# Who may read /api/amiibo-stats/ from a logged-in browser session. This lives
# in Firestore rather than in source because the repo is public — committing the
# addresses would publish them permanently in git history — and rather than in
# an env var because that would mean a Terraform change. It is also editable
# from the Firestore console without a redeploy.


def get_owner_emails() -> set:
    """Read the operator allowlist. Returns an empty set when unset."""
    doc = get_client().collection(APP_CONFIG_COLLECTION).document(OWNERS_DOC_ID).get()
    if not doc.exists:
        return set()
    raw = (doc.to_dict() or {}).get("emails") or []
    if isinstance(raw, str):  # tolerate a console edit that used a plain string
        raw = raw.split(",")
    return {str(e).strip().lower() for e in raw if str(e).strip()}


def set_owner_emails(emails) -> set:
    """Replace the operator allowlist. Returns what was stored."""
    normalized = sorted({str(e).strip().lower() for e in emails if str(e).strip()})
    (
        get_client()
        .collection(APP_CONFIG_COLLECTION)
        .document(OWNERS_DOC_ID)
        .set({"emails": normalized, "updated_at": datetime.now(timezone.utc)})
    )
    return set(normalized)
