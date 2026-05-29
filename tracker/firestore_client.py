import os
from functools import lru_cache

from google.cloud import firestore

COMMENTS_COLLECTION = "amiibo_comments"


@lru_cache(maxsize=1)
def get_client() -> firestore.Client:
    project = os.environ.get("GCP_PROJECT_ID")
    return firestore.Client(project=project) if project else firestore.Client()


def list_comments(amiibo_id: str, limit: int = 50) -> list[dict]:
    docs = (
        get_client()
        .collection(COMMENTS_COLLECTION)
        .where(filter=firestore.FieldFilter("amiibo_id", "==", amiibo_id))
        .where(filter=firestore.FieldFilter("is_hidden", "==", False))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


def add_comment(
    amiibo_id: str, user_email: str, display_name: str, body: str
) -> str:
    _, doc_ref = get_client().collection(COMMENTS_COLLECTION).add(
        {
            "amiibo_id": amiibo_id,
            "user_email": user_email,
            "display_name": display_name,
            "body": body,
            "created_at": firestore.SERVER_TIMESTAMP,
            "is_hidden": False,
        }
    )
    return doc_ref.id
