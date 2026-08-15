"""Aggregate stats over every user's tracked-amiibo blob.

Shared by `manage.py amiibo_stats` and the `/api/amiibo-stats/` endpoint so the
two can never drift. Everything here returns plain data; formatting (text, JSON,
CSV) is the caller's job.
"""

import hashlib
import hmac
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from django.conf import settings

from tracker import firestore_client
from tracker.collection_snapshot import _Catalog, stable_id


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------
#
# The endpoint exposes aggregate collection data, so it needs a shared secret.
# Rather than introduce a new env var (which would mean a Terraform change, and
# an env var added by hand to Cloud Run would be wiped by the next apply), the
# token is *derived* from DJANGO_SECRET_KEY — already on the container, and the
# value Django exists to derive things from. The label keeps this token
# unrelated to any other use of the key, and HMAC means the token never reveals
# the key. AMIIBO_STATS_TOKEN overrides it if a dedicated secret is ever wired.

_TOKEN_LABEL = b"amiibo-stats-api/v1"
_UNSAFE_DEFAULT = "unsafe-default-key"


def api_token() -> str | None:
    """The token callers must present, or None when none can be derived."""
    explicit = (os.environ.get("AMIIBO_STATS_TOKEN") or "").strip()
    if explicit:
        return explicit

    secret = (getattr(settings, "SECRET_KEY", "") or "").strip()
    if not secret or secret == _UNSAFE_DEFAULT:
        return None
    return hmac.new(secret.encode("utf-8"), _TOKEN_LABEL, hashlib.sha256).hexdigest()


def token_is_valid(presented) -> bool:
    """Constant-time check of a presented token. Fails closed."""
    expected = api_token()
    if not expected or not presented:
        return False
    return hmac.compare_digest(str(presented), expected)


# ---------------------------------------------------------------------------
# Owner sessions
# ---------------------------------------------------------------------------
#
# Being logged in is NOT enough: anyone with a Google account can sign in to
# goozamiibo.com, so a bare "is authenticated" check would hand every user the
# aggregate collection data. Access is restricted to named addresses instead.
#
# The list lives in Firestore (app_config/owners, set via `manage.py
# set_owners`): the repo is public, so committing the addresses would publish
# them in git history forever, and an env var would mean a Terraform change.
# ADMIN_EMAILS still wins when set, for local development and tests.
# DAILY_REPORT_TO_EMAIL is the last-resort fallback so a missing config document
# does not lock the owner out entirely.

_OWNER_CACHE_KEY = "amiibo:owner_emails"
_OWNER_CACHE_TIMEOUT = 300


def _split(raw) -> set:
    return {part.strip().lower() for part in (raw or "").split(",") if part.strip()}


def owner_emails() -> set:
    """Addresses allowed to read the stats from a logged-in browser session."""
    explicit = _split(os.environ.get("ADMIN_EMAILS"))
    if explicit:
        return explicit

    from django.core.cache import cache

    cached = cache.get(_OWNER_CACHE_KEY)
    if cached is not None:
        return set(cached)

    try:
        owners = firestore_client.get_owner_emails()
    except Exception:
        # A Firestore blip must not silently widen or close access mid-flight;
        # fall through to the configured fallback below.
        logger.debug("owner-allowlist-read-failed", exc_info=True)
        owners = set()

    if not owners:
        owners = _split(getattr(settings, "DAILY_REPORT_TO_EMAIL", ""))

    cache.set(_OWNER_CACHE_KEY, sorted(owners), _OWNER_CACHE_TIMEOUT)
    return owners


def clear_owner_cache() -> None:
    """Drop the cached allowlist so a change takes effect immediately."""
    from django.core.cache import cache

    cache.delete(_OWNER_CACHE_KEY)


def is_owner_session(request) -> bool:
    """True when the request carries a logged-in session owned by an operator.

    Fails closed: with no owner configured, nobody qualifies.
    """
    session = getattr(request, "session", None)
    email = (session.get("user_email") if session is not None else None) or ""
    owners = owner_emails()
    return bool(owners) and email.strip().lower() in owners


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def catalog() -> dict:
    """Map every known amiibo's stable id to its name."""
    return {stable_id(a): a.get("name", "") for a in _Catalog()._fetch_local_amiibos()}


def tally(rows):
    """Count collected/favorited holders per amiibo across all user blobs.

    Users with no blob yet are excluded from ``total_users`` so they cannot
    drag every percentage down.
    """
    collected, favorited = Counter(), Counter()
    total_users = 0
    for row in rows:
        entries = firestore_client.decode_amiibos(row.get("amiibos"))
        if not entries:
            continue
        total_users += 1
        for entry in entries:
            amiibo_id = entry.get("id")
            if not amiibo_id:
                continue
            if entry.get("collected"):
                collected[amiibo_id] += 1
            if entry.get("favorite"):
                favorited[amiibo_id] += 1
    return collected, favorited, total_users


def _entry(names, amiibo_id, count, total_users):
    return {
        "id": amiibo_id,
        "name": names.get(amiibo_id) or "(not in local catalog)",
        "users": count,
        "pct": round(count / total_users * 100, 1) if total_users else 0.0,
    }


def build_report(top: int = 10) -> dict:
    """Everything the overview shows, as plain data."""
    names = catalog()
    collected, favorited, total_users = tally(firestore_client.list_user_interactions())

    owned = [aid for aid in names if collected[aid] > 0]
    unowned = [aid for aid in names if collected[aid] == 0]
    faved = [aid for aid in names if favorited[aid] > 0]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_users": total_users,
        "catalog_size": len(names),
        "owned_amiibo_count": len(owned),
        "most_collected": [
            _entry(names, aid, collected[aid], total_users)
            for aid in sorted(owned, key=lambda a: (-collected[a], names[a]))[:top]
        ],
        "rarest_owned": [
            _entry(names, aid, collected[aid], total_users)
            for aid in sorted(owned, key=lambda a: (collected[a], names[a]))[:top]
        ],
        "most_favorited": [
            _entry(names, aid, favorited[aid], total_users)
            for aid in sorted(faved, key=lambda a: (-favorited[a], names[a]))[:top]
        ],
        "owned_by_nobody": {
            "count": len(unowned),
            "sample": [
                _entry(names, aid, 0, total_users)
                for aid in sorted(unowned, key=lambda a: names[a])[:top]
            ],
        },
    }


def lookup(needle: str, limit: int = 20) -> list[dict]:
    """Find amiibos by stable id, exact name, then substring — in that order."""
    names = catalog()
    collected, favorited, total_users = tally(firestore_client.list_user_interactions())

    lowered = (needle or "").lower()
    matches = [aid for aid in names if aid == needle]
    if not matches:
        matches = [aid for aid, name in names.items() if name.lower() == lowered]
    if not matches:
        matches = [
            aid for aid, name in names.items() if lowered and lowered in name.lower()
        ]

    return [
        {
            **_entry(names, aid, collected[aid], total_users),
            "favorited_by": favorited[aid],
            "missing_from": total_users - collected[aid],
            "total_users": total_users,
        }
        for aid in sorted(matches, key=lambda a: (-collected[a], names[a]))[:limit]
    ]


def full_table() -> list[dict]:
    """One row per catalog amiibo, for CSV export."""
    names = catalog()
    collected, favorited, total_users = tally(firestore_client.list_user_interactions())
    return [
        {
            "amiibo_id": aid,
            "name": name,
            "collected_by": collected[aid],
            "favorited_by": favorited[aid],
            "missing_from": total_users - collected[aid],
            "collected_pct": (
                round(collected[aid] / total_users * 100, 1) if total_users else 0.0
            ),
        }
        for aid, name in sorted(names.items(), key=lambda kv: kv[1])
    ]
