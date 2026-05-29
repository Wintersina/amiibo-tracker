import os
from functools import lru_cache

from google.cloud import firestore

AMIIBO_COMMENTS_COLLECTION = "amiibo_comments"
BLOG_COMMENTS_COLLECTION = "blog_comments"


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
                "created_at": firestore.SERVER_TIMESTAMP,
                "is_hidden": False,
            }
        )
    )
    return doc_ref.id


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
