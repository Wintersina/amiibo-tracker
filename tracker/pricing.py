import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from time import monotonic
from urllib.parse import urlencode

import requests
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import firestore
from google.cloud.firestore_v1.field_path import FieldPath

from tracker.firestore_client import get_client


logger = logging.getLogger(__name__)


class EbayAuthenticationError(RuntimeError):
    """Raised when eBay rejects the configured client credentials."""


AMIIBO_PRICE_LATEST_COLLECTION = "amiibo_price_latest"
AMIIBO_PRICE_SNAPSHOTS_COLLECTION = "amiibo_price_snapshots"
AMIIBO_PRICE_INDEX_COLLECTION = "amiibo_price_index"
AMIIBO_PRICE_INDEX_DOCUMENT = "latest"
LOCAL_PRICE_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / "amiibo_price_cache.local.json"
)

EBAY_SEARCH_PAGE_URL = "https://www.ebay.com/sch/i.html"
EBAY_PRODUCTION_API_BASE_URL = "https://api.ebay.com"
EBAY_SANDBOX_API_BASE_URL = "https://api.sandbox.ebay.com"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

EXCLUDED_TITLE_TERMS = {
    "amiibo card",
    "amiibo cards",
    "nfc",
    "coin",
    "coins",
    "tag",
    "tags",
    "lot",
    "bundle",
    "custom",
    "repro",
    "reproduction",
    "damaged",
    "for parts",
    "repair",
    "replacement",
    "protector",
    "case",
    "box only",
    "empty box",
    "no figure",
    "choose",
    "pick",
    "random",
    "mystery",
    "plush",
    "keychain",
}

NAME_STOP_WORDS = {
    "amiibo",
    "the",
    "and",
    "with",
    "for",
    "super",
    "bros",
    "series",
    "figure",
    "nintendo",
}


@dataclass(frozen=True)
class EbayConfig:
    client_id: str
    client_secret: str
    marketplace_id: str = "EBAY_US"
    environment: str = "production"

    @classmethod
    def from_env(cls):
        client_id = os.environ.get("EBAY_CLIENT_ID", "").strip()
        client_secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
        marketplace_id = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US").strip()
        environment = configured_ebay_environment()
        if not client_id or not client_secret:
            return None
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            marketplace_id=marketplace_id or "EBAY_US",
            environment=environment,
        )

    @property
    def api_base_url(self) -> str:
        if self.environment == "sandbox":
            return EBAY_SANDBOX_API_BASE_URL
        return EBAY_PRODUCTION_API_BASE_URL

    @property
    def token_url(self) -> str:
        return f"{self.api_base_url}/identity/v1/oauth2/token"

    @property
    def browse_search_url(self) -> str:
        return f"{self.api_base_url}/buy/browse/v1/item_summary/search"


def configured_ebay_environment() -> str:
    environment = (
        os.environ.get("EBAY_ENV") or os.environ.get("EBAY_ENVIRONMENT") or "production"
    ).strip()
    if os.environ.get("EBAY_SANDBOX") == "1":
        environment = "sandbox"
    environment = environment.lower()
    if environment not in {"production", "sandbox"}:
        return "production"
    return environment


def price_refresh_runtime_config() -> dict:
    return {
        "ebay_client_id_configured": bool(os.environ.get("EBAY_CLIENT_ID", "").strip()),
        "ebay_client_secret_configured": bool(
            os.environ.get("EBAY_CLIENT_SECRET", "").strip()
        ),
        "ebay_environment": configured_ebay_environment(),
        "ebay_marketplace_id": os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US")
        or "EBAY_US",
        "env_name": os.environ.get("ENV_NAME", ""),
        "local_cache_enabled": local_price_cache_enabled(),
    }


def amiibo_price_id(amiibo: dict) -> str:
    head = (amiibo.get("head") or "").strip()
    tail = (amiibo.get("tail") or "").strip()
    return f"{head}-{tail}" if head and tail else ""


def build_ebay_search_query(amiibo: dict) -> str:
    parts = [amiibo.get("name") or "", amiibo.get("amiiboSeries") or "", "amiibo"]
    query = " ".join(part.strip() for part in parts if part and part.strip())
    return " ".join(query.split())[:100]


def build_ebay_search_url(amiibo: dict) -> str:
    return (
        f"{EBAY_SEARCH_PAGE_URL}?{urlencode({'_nkw': build_ebay_search_query(amiibo)})}"
    )


def _parse_money(value) -> int | None:
    try:
        dollars = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if dollars <= 0:
        return None
    return int((dollars * 100).quantize(Decimal("1")))


def _item_total_cents(item: dict) -> int | None:
    price = item.get("price") or {}
    cents = _parse_money(price.get("value"))
    if cents is None:
        return None

    shipping_options = item.get("shippingOptions") or []
    shipping_cents = 0
    if shipping_options:
        shipping_cost = (shipping_options[0] or {}).get("shippingCost") or {}
        parsed_shipping = _parse_money(shipping_cost.get("value"))
        if parsed_shipping is not None:
            shipping_cents = parsed_shipping

    return cents + shipping_cents


def _title_matches_amiibo(title: str, amiibo: dict) -> bool:
    normalized_title = title.lower()
    if "amiibo" not in normalized_title:
        return False
    excluded_terms = set(EXCLUDED_TITLE_TERMS)
    amiibo_type = (amiibo.get("type") or "").lower()
    amiibo_series = (amiibo.get("amiiboSeries") or "").lower()
    if "card" in amiibo_type or "card" in amiibo_series:
        excluded_terms -= {"amiibo card", "amiibo cards"}
    if any(term in normalized_title for term in excluded_terms):
        return False

    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (amiibo.get("name") or "").lower())
        if len(token) > 2 and token not in NAME_STOP_WORDS
    ]
    if not tokens:
        return True

    required_matches = min(2, len(tokens))
    return sum(1 for token in tokens if token in normalized_title) >= required_matches


def _condition_bucket(item: dict) -> str | None:
    condition = (item.get("condition") or "").lower()
    title = (item.get("title") or "").lower()

    if any(term in title for term in ("new in box", "nib", "sealed", "unopened")):
        return "new"
    if condition.startswith("new"):
        return "new"
    if any(term in title for term in ("loose", "oob", "out of box", "opened")):
        return "loose"
    if "used" in condition or "open box" in condition:
        return "loose"

    return None


def _trim_outliers(values: list[int]) -> list[int]:
    if len(values) < 4:
        return values

    midpoint = median(values)
    lower = midpoint / 3
    upper = midpoint * 3
    trimmed = [value for value in values if lower <= value <= upper]
    return trimmed or values


def _median_cents(values: list[int]) -> int | None:
    values = _trim_outliers(values)
    if not values:
        return None
    return int(median(values))


def _confidence(sample_count: int) -> str:
    if sample_count >= 8:
        return "high"
    if sample_count >= 4:
        return "medium"
    if sample_count >= 1:
        return "low"
    return "unavailable"


def estimate_prices_from_ebay_items(amiibo: dict, items: list[dict]) -> dict:
    loose_values = []
    new_values = []
    currency = "USD"

    for item in items:
        title = item.get("title") or ""
        if not _title_matches_amiibo(title, amiibo):
            continue

        item_currency = (item.get("price") or {}).get("currency")
        if item_currency:
            currency = item_currency

        cents = _item_total_cents(item)
        if cents is None:
            continue

        bucket = _condition_bucket(item)
        if bucket == "new":
            new_values.append(cents)
        elif bucket == "loose":
            loose_values.append(cents)

    loose_estimate = _median_cents(loose_values)
    new_estimate = _median_cents(new_values)
    sample_count = len(loose_values) + len(new_values)

    return {
        "currency": currency,
        "loose_estimate_cents": loose_estimate,
        "new_estimate_cents": new_estimate,
        "loose_sample_count": len(loose_values),
        "new_sample_count": len(new_values),
        "sample_count": sample_count,
        "confidence": _confidence(sample_count),
        "source": "ebay_browse_api",
        "source_label": "eBay active listings",
        "status": "estimated" if sample_count else "unavailable",
    }


def format_price(cents: int | None, currency: str = "USD") -> str:
    if cents is None:
        return ""
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{cents / 100:.0f}"


def normalize_pricing_for_display(amiibo: dict, pricing: dict | None) -> dict:
    search_url = build_ebay_search_url(amiibo)
    base = {
        "source_url": search_url,
        "source_label": "eBay listings",
        "has_estimate": False,
        "status": "pending",
        "confidence": "unavailable",
        "display": "Check eBay",
        "loose_display": "",
        "new_display": "",
        "sample_count": 0,
        "snapshot_date": "",
    }

    if not pricing:
        return base

    currency = pricing.get("currency") or "USD"
    loose_display = format_price(pricing.get("loose_estimate_cents"), currency)
    new_display = format_price(pricing.get("new_estimate_cents"), currency)
    has_estimate = bool(loose_display or new_display)
    display_parts = []
    if loose_display:
        display_parts.append(f"Loose {loose_display}")
    if new_display:
        display_parts.append(f"NIB {new_display}")

    return {
        **base,
        **pricing,
        "source_url": pricing.get("source_url") or search_url,
        "source_label": pricing.get("source_label") or base["source_label"],
        "has_estimate": has_estimate,
        "display": " / ".join(display_parts) if display_parts else base["display"],
        "loose_display": loose_display,
        "new_display": new_display,
        "sample_count": pricing.get("sample_count") or 0,
        "snapshot_date": pricing.get("snapshot_date") or "",
    }


def _parse_snapshot_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def pricing_snapshot_is_current(pricing: dict | None, snapshot_date: date) -> bool:
    if not pricing:
        return False
    return _parse_snapshot_date(pricing.get("snapshot_date")) == snapshot_date


def _format_chart_date(value) -> str:
    parsed = _parse_snapshot_date(value)
    if not parsed:
        return "Latest"
    return f"{parsed.strftime('%b')} {parsed.day}"


def _format_change_percent(first_cents: int | None, last_cents: int | None) -> str:
    if not first_cents or not last_cents or first_cents <= 0:
        return ""
    change = ((last_cents - first_cents) / first_cents) * 100
    if abs(change) < 0.5:
        return "0%"
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.0f}%"


def build_price_chart_data(pricing: dict, history: list[dict] | None = None) -> dict:
    points = []
    seen_dates = set()

    for snapshot in history or []:
        loose_cents = snapshot.get("loose_estimate_cents")
        new_cents = snapshot.get("new_estimate_cents")
        if loose_cents is None and new_cents is None:
            continue

        snapshot_date = snapshot.get("snapshot_date") or snapshot.get("date") or ""
        seen_dates.add(snapshot_date)
        currency = snapshot.get("currency") or pricing.get("currency") or "USD"
        points.append(
            {
                "date": snapshot_date,
                "sort_date": _parse_snapshot_date(snapshot_date) or date.min,
                "label": _format_chart_date(snapshot_date),
                "loose_cents": loose_cents,
                "new_cents": new_cents,
                "loose_display": format_price(loose_cents, currency),
                "new_display": format_price(new_cents, currency),
            }
        )

    current_date = pricing.get("snapshot_date") or ""
    if pricing.get("has_estimate") and current_date not in seen_dates:
        currency = pricing.get("currency") or "USD"
        points.append(
            {
                "date": current_date,
                "sort_date": _parse_snapshot_date(current_date) or date.max,
                "label": _format_chart_date(current_date),
                "loose_cents": pricing.get("loose_estimate_cents"),
                "new_cents": pricing.get("new_estimate_cents"),
                "loose_display": pricing.get("loose_display")
                or format_price(pricing.get("loose_estimate_cents"), currency),
                "new_display": pricing.get("new_display")
                or format_price(pricing.get("new_estimate_cents"), currency),
            }
        )

    points.sort(key=lambda point: point["sort_date"])
    values = [
        value
        for point in points
        for value in (point.get("loose_cents"), point.get("new_cents"))
        if value is not None
    ]

    if not values:
        return {
            "has_chart": False,
            "points": [],
            "recent_points": [],
            "min_display": "",
            "max_display": "",
            "loose_polyline": "",
            "new_polyline": "",
            "has_loose_line": False,
            "has_new_line": False,
            "loose_change": "",
            "new_change": "",
        }

    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        padding = max(100, int(min_value * 0.1))
        min_value = max(0, min_value - padding)
        max_value = max_value + padding

    value_range = max_value - min_value

    def x_for(index: int) -> float:
        if len(points) == 1:
            return 50
        return round((index / (len(points) - 1)) * 100, 2)

    def y_for(value: int | None) -> float | None:
        if value is None:
            return None
        return round(54 - ((value - min_value) / value_range) * 48, 2)

    loose_polyline = []
    new_polyline = []
    for index, point in enumerate(points):
        point["x"] = x_for(index)
        point["loose_y"] = y_for(point.get("loose_cents"))
        point["new_y"] = y_for(point.get("new_cents"))
        point["has_loose"] = point["loose_y"] is not None
        point["has_new"] = point["new_y"] is not None
        if point["has_loose"]:
            point["loose_point"] = f"{point['x']},{point['loose_y']}"
            loose_polyline.append(point["loose_point"])
        if point["has_new"]:
            point["new_point"] = f"{point['x']},{point['new_y']}"
            new_polyline.append(point["new_point"])

    loose_values = [point.get("loose_cents") for point in points if point["has_loose"]]
    new_values = [point.get("new_cents") for point in points if point["has_new"]]

    return {
        "has_chart": True,
        "points": points,
        "recent_points": list(reversed(points[-5:])),
        "min_display": format_price(min_value, pricing.get("currency") or "USD"),
        "max_display": format_price(max_value, pricing.get("currency") or "USD"),
        "loose_polyline": " ".join(loose_polyline),
        "new_polyline": " ".join(new_polyline),
        "has_loose_line": len(loose_polyline) > 1,
        "has_new_line": len(new_polyline) > 1,
        "loose_change": _format_change_percent(
            loose_values[0] if loose_values else None,
            loose_values[-1] if loose_values else None,
        ),
        "new_change": _format_change_percent(
            new_values[0] if new_values else None,
            new_values[-1] if new_values else None,
        ),
    }


def pricing_reads_enabled() -> bool:
    if local_price_cache_enabled():
        return True
    if os.environ.get("AMIIBO_PRICE_DISABLE_READS") == "1":
        return False
    if os.environ.get("AMIIBO_PRICE_ENABLE_LOCAL_READS") == "1":
        return True
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return True
    return os.environ.get("ENV_NAME") == "production"


def local_price_cache_enabled() -> bool:
    if os.environ.get("AMIIBO_PRICE_USE_LOCAL_CACHE") == "1":
        return True
    if os.environ.get("ENV_NAME") == "production":
        return False
    return _local_price_cache_path().exists()


def _local_price_cache_path() -> Path:
    configured_path = os.environ.get("AMIIBO_PRICE_LOCAL_CACHE_PATH", "").strip()
    return Path(configured_path) if configured_path else LOCAL_PRICE_CACHE_PATH


class EbayBrowseClient:
    def __init__(self, config: EbayConfig | None = None, session=None):
        self.config = config or EbayConfig.from_env()
        self.session = session or requests.Session()
        self._token = None
        self._token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    @property
    def configured(self) -> bool:
        return self.config is not None

    def _access_token(self) -> str:
        if not self.config:
            raise RuntimeError("eBay credentials are not configured.")

        now = datetime.now(timezone.utc)
        if self._token and now < self._token_expires_at:
            return self._token

        raw_credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded_credentials = base64.b64encode(raw_credentials.encode()).decode()
        response = self.session.post(
            self.config.token_url,
            headers={
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
            timeout=20,
        )
        if response.status_code in (401, 403):
            raise EbayAuthenticationError(
                "eBay rejected the configured credentials for "
                f"{self.config.environment}. Check EBAY_ENV and make sure the "
                "client id and client secret are from the same eBay keyset."
            )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 7200))
        self._token_expires_at = now + timedelta(seconds=max(expires_in - 120, 60))
        return self._token

    def ensure_authenticated(self):
        self._access_token()

    def search_amiibo(self, amiibo: dict, limit: int = 50) -> list[dict]:
        token = self._access_token()
        response = self.session.get(
            self.config.browse_search_url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
            },
            params={
                "q": build_ebay_search_query(amiibo),
                "limit": str(limit),
                "filter": "buyingOptions:{FIXED_PRICE},price:[3..500],priceCurrency:USD",
                "fieldgroups": "EXTENDED",
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("itemSummaries", []) or []


class AmiiboPricingRepository:
    def __init__(self, client=None):
        self.client = client or get_client()

    def get_latest_map(self, amiibo_ids: list[str]) -> dict[str, dict]:
        wanted_ids = [amiibo_id for amiibo_id in amiibo_ids if amiibo_id]
        if not wanted_ids:
            return {}

        latest = {}
        try:
            index_doc = (
                self.client.collection(AMIIBO_PRICE_INDEX_COLLECTION)
                .document(AMIIBO_PRICE_INDEX_DOCUMENT)
                .get()
            )
            if index_doc.exists:
                index_prices = (index_doc.to_dict() or {}).get("prices") or {}
                latest.update(
                    {
                        amiibo_id: index_prices[amiibo_id]
                        for amiibo_id in wanted_ids
                        if amiibo_id in index_prices
                    }
                )
        except Exception as exc:
            logger.warning("amiibo-pricing-index-read-failed: %s", exc)

        missing_ids = [amiibo_id for amiibo_id in wanted_ids if amiibo_id not in latest]
        if not missing_ids:
            return latest

        fallback_limit = int(os.environ.get("AMIIBO_PRICE_DOC_FALLBACK_LIMIT", "50"))
        if len(missing_ids) > fallback_limit:
            return latest

        doc_refs = [
            self.client.collection(AMIIBO_PRICE_LATEST_COLLECTION).document(amiibo_id)
            for amiibo_id in missing_ids
        ]

        for doc in self.client.get_all(doc_refs):
            if doc.exists:
                latest[doc.id] = doc.to_dict() or {}
        return latest

    def get_history(self, amiibo_id: str, days: int = 183) -> list[dict]:
        if not amiibo_id:
            return []

        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days)
        daily = (
            self.client.collection(AMIIBO_PRICE_SNAPSHOTS_COLLECTION)
            .document(amiibo_id)
            .collection("daily")
        )

        snapshots = []
        for doc in daily.stream():
            payload = doc.to_dict() or {}
            snapshot_date = payload.get("snapshot_date") or doc.id
            parsed_date = _parse_snapshot_date(snapshot_date)
            if parsed_date and parsed_date < cutoff_date:
                continue
            snapshots.append(
                {
                    **payload,
                    "snapshot_date": (
                        parsed_date.isoformat() if parsed_date else snapshot_date
                    ),
                }
            )

        snapshots.sort(
            key=lambda snapshot: _parse_snapshot_date(snapshot.get("snapshot_date"))
            or date.min
        )
        return snapshots

    def save_snapshot(self, amiibo_id: str, pricing: dict, snapshot_date: date):
        latest_ref = self.client.collection(AMIIBO_PRICE_LATEST_COLLECTION).document(
            amiibo_id
        )
        snapshots_parent_ref = self.client.collection(
            AMIIBO_PRICE_SNAPSHOTS_COLLECTION
        ).document(amiibo_id)
        snapshots_ref = snapshots_parent_ref.collection("daily").document(
            snapshot_date.isoformat()
        )

        payload = {
            **pricing,
            "amiibo_id": amiibo_id,
            "snapshot_date": snapshot_date.isoformat(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        batch = self.client.batch()
        batch.set(latest_ref, payload)
        batch.set(
            snapshots_parent_ref,
            {
                "amiibo_id": amiibo_id,
                "latest_snapshot_date": snapshot_date.isoformat(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        batch.set(snapshots_ref, payload)
        batch.commit()

    def save_latest_index(self, pricing_by_id: dict[str, dict], snapshot_date: date):
        if not pricing_by_id:
            return

        prices = {}
        for amiibo_id, pricing in pricing_by_id.items():
            prices[amiibo_id] = {
                **pricing,
                "amiibo_id": amiibo_id,
                "snapshot_date": snapshot_date.isoformat(),
            }

        self.client.collection(AMIIBO_PRICE_INDEX_COLLECTION).document(
            AMIIBO_PRICE_INDEX_DOCUMENT
        ).set(
            {
                "prices": prices,
                "snapshot_date": snapshot_date.isoformat(),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    def prune_old_snapshots(self, amiibo_id: str, before_date: date) -> int:
        daily = (
            self.client.collection(AMIIBO_PRICE_SNAPSHOTS_COLLECTION)
            .document(amiibo_id)
            .collection("daily")
        )
        old_docs = daily.where(
            filter=firestore.FieldFilter(
                FieldPath.document_id(), "<", before_date.isoformat()
            )
        ).stream()

        deleted = 0
        batch = self.client.batch()
        for doc in old_docs:
            batch.delete(doc.reference)
            deleted += 1
            if deleted % 450 == 0:
                batch.commit()
                batch = self.client.batch()
        if deleted % 450:
            batch.commit()
        return deleted


class LocalAmiiboPricingRepository:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else _local_price_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_cache(self) -> dict:
        if not self.path.exists():
            return {"prices": {}, "history": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("local-price-cache-read-failed: %s", self.path)
            return {"prices": {}, "history": {}}
        return {
            "prices": payload.get("prices") or {},
            "history": payload.get("history") or {},
        }

    def _write_cache(self, payload: dict):
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def get_latest_map(self, amiibo_ids: list[str]) -> dict[str, dict]:
        prices = self._read_cache()["prices"]
        return {
            amiibo_id: prices[amiibo_id]
            for amiibo_id in amiibo_ids
            if amiibo_id and amiibo_id in prices
        }

    def get_history(self, amiibo_id: str, days: int = 183) -> list[dict]:
        history = self._read_cache()["history"].get(amiibo_id) or []
        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days)
        snapshots = []
        for snapshot in history:
            parsed_date = _parse_snapshot_date(snapshot.get("snapshot_date"))
            if parsed_date and parsed_date < cutoff_date:
                continue
            snapshots.append(snapshot)
        snapshots.sort(
            key=lambda snapshot: _parse_snapshot_date(snapshot.get("snapshot_date"))
            or date.min
        )
        return snapshots

    def save_snapshot(self, amiibo_id: str, pricing: dict, snapshot_date: date):
        payload = self._read_cache()
        snapshot_payload = {
            **pricing,
            "amiibo_id": amiibo_id,
            "snapshot_date": snapshot_date.isoformat(),
        }
        payload["prices"][amiibo_id] = snapshot_payload
        history = payload["history"].setdefault(amiibo_id, [])
        history = [
            snapshot
            for snapshot in history
            if snapshot.get("snapshot_date") != snapshot_date.isoformat()
        ]
        history.append(snapshot_payload)
        payload["history"][amiibo_id] = history
        self._write_cache(payload)

    def save_latest_index(self, pricing_by_id: dict[str, dict], snapshot_date: date):
        payload = self._read_cache()
        for amiibo_id, pricing in pricing_by_id.items():
            payload["prices"][amiibo_id] = {
                **pricing,
                "amiibo_id": amiibo_id,
                "snapshot_date": snapshot_date.isoformat(),
            }
        self._write_cache(payload)

    def prune_old_snapshots(self, amiibo_id: str, before_date: date) -> int:
        payload = self._read_cache()
        history = payload["history"].get(amiibo_id) or []
        retained = []
        deleted = 0
        for snapshot in history:
            parsed_date = _parse_snapshot_date(snapshot.get("snapshot_date"))
            if parsed_date and parsed_date < before_date:
                deleted += 1
                continue
            retained.append(snapshot)
        payload["history"][amiibo_id] = retained
        self._write_cache(payload)
        return deleted


def get_pricing_repository():
    if local_price_cache_enabled():
        return LocalAmiiboPricingRepository()
    return AmiiboPricingRepository()


def enrich_amiibos_with_pricing(amiibos: list[dict], repository=None) -> list[dict]:
    amiibo_ids = [amiibo_price_id(amiibo) for amiibo in amiibos]
    latest_map = {}
    if repository or pricing_reads_enabled():
        try:
            latest_map = (repository or get_pricing_repository()).get_latest_map(
                amiibo_ids
            )
        except Exception as exc:
            logger.warning("amiibo-pricing-read-failed: %s", exc)

    for amiibo in amiibos:
        price_id = amiibo_price_id(amiibo)
        pricing = latest_map.get(price_id)
        amiibo["pricing"] = normalize_pricing_for_display(amiibo, pricing)

    return amiibos


def get_amiibo_pricing_context(amiibo: dict, repository=None) -> dict:
    price_id = amiibo_price_id(amiibo)
    latest = None
    history = []

    if price_id and (repository or pricing_reads_enabled()):
        try:
            price_repository = repository or get_pricing_repository()
            latest = price_repository.get_latest_map([price_id]).get(price_id)
            history = price_repository.get_history(price_id)
        except Exception as exc:
            logger.warning("amiibo-detail-pricing-read-failed: %s", exc)

    display_pricing = normalize_pricing_for_display(amiibo, latest)
    return {
        "pricing": display_pricing,
        "price_chart": build_price_chart_data(display_pricing, history),
    }


class AmiiboPriceRefreshService:
    def __init__(self, ebay_client=None, repository=None, today: date | None = None):
        self.ebay_client = ebay_client or EbayBrowseClient()
        self.repository = repository
        self.today = today or datetime.now(timezone.utc).date()

    def _log_result(self, result: dict, started_at: float, runtime_config: dict):
        payload = {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "environment": result.get("environment"),
            "dry_run": result.get("dry_run"),
            "processed": result.get("processed", 0),
            "updated": result.get("updated", 0),
            "priced": result.get("priced", 0),
            "unavailable": result.get("unavailable", 0),
            "already_current": result.get("already_current", 0),
            "failed": result.get("failed", 0),
            "index_failed": result.get("index_failed", 0),
            "elapsed_ms": round((monotonic() - started_at) * 1000),
            "runtime_config": runtime_config,
        }
        log_method = logger.info
        if (
            result.get("status") in {"partial", "skipped"}
            or result.get("failed")
            or result.get("index_failed")
        ):
            log_method = logger.warning
        log_method("amiibo-price-refresh-finished | context=%s", json.dumps(payload))

    def refresh(
        self,
        amiibos: list[dict],
        limit: int | None = None,
        save: bool = True,
    ) -> dict:
        started_at = monotonic()
        environment = getattr(
            getattr(self.ebay_client, "config", None),
            "environment",
            configured_ebay_environment(),
        )
        runtime_config = price_refresh_runtime_config()
        runtime_config["ebay_environment"] = environment
        logger.info(
            "amiibo-price-refresh-started | context=%s",
            json.dumps(
                {
                    "amiibo_count": len(amiibos),
                    "limit": limit,
                    "save": save,
                    "environment": environment,
                    "runtime_config": runtime_config,
                }
            ),
        )

        if not self.ebay_client.configured:
            result = {
                "status": "skipped",
                "reason": "ebay_credentials_missing",
                "environment": environment,
                "processed": 0,
                "updated": 0,
                "priced": 0,
                "unavailable": 0,
                "already_current": 0,
                "failed": 0,
                "index_failed": 0,
            }
            self._log_result(result, started_at, runtime_config)
            return result

        retention_days = int(os.environ.get("AMIIBO_PRICE_RETENTION_DAYS", "183"))
        cutoff_date = self.today - timedelta(days=retention_days)
        try:
            repository = self.repository or (get_pricing_repository() if save else None)
        except DefaultCredentialsError:
            result = {
                "status": "skipped",
                "reason": "firestore_credentials_missing",
                "environment": environment,
                "processed": 0,
                "updated": 0,
                "priced": 0,
                "unavailable": 0,
                "already_current": 0,
                "failed": 0,
                "index_failed": 0,
            }
            self._log_result(result, started_at, runtime_config)
            return result

        current_price_map = {}
        current_check_ids = []
        can_check_current_prices = (
            save and repository and hasattr(repository, "get_latest_map")
        )
        if can_check_current_prices:
            for amiibo in amiibos:
                if limit is not None and len(current_check_ids) >= limit:
                    break
                price_id = amiibo_price_id(amiibo)
                if price_id:
                    current_check_ids.append(price_id)
            try:
                current_price_map = repository.get_latest_map(current_check_ids)
            except Exception as exc:
                logger.warning("amiibo-price-current-read-failed: %s", exc)

        needs_ebay_auth = not save
        if save:
            needs_ebay_auth = not can_check_current_prices or any(
                not pricing_snapshot_is_current(
                    current_price_map.get(price_id), self.today
                )
                for price_id in current_check_ids
            )

        if needs_ebay_auth:
            try:
                if hasattr(self.ebay_client, "ensure_authenticated"):
                    self.ebay_client.ensure_authenticated()
            except EbayAuthenticationError as exc:
                result = {
                    "status": "skipped",
                    "reason": "ebay_auth_failed",
                    "message": str(exc),
                    "environment": environment,
                    "processed": 0,
                    "updated": 0,
                    "priced": 0,
                    "unavailable": 0,
                    "already_current": 0,
                    "failed": 0,
                    "index_failed": 0,
                }
                self._log_result(result, started_at, runtime_config)
                return result
            except requests.RequestException as exc:
                result = {
                    "status": "skipped",
                    "reason": "ebay_token_request_failed",
                    "message": str(exc),
                    "environment": environment,
                    "processed": 0,
                    "updated": 0,
                    "priced": 0,
                    "unavailable": 0,
                    "already_current": 0,
                    "failed": 0,
                    "index_failed": 0,
                }
                self._log_result(result, started_at, runtime_config)
                return result

        updated = 0
        priced = 0
        unavailable = 0
        already_current = 0
        failed = 0
        index_failed = 0
        processed = 0
        errors = []
        updated_prices = {}
        pending_index_prices = {}
        index_flush_interval = max(
            int(os.environ.get("AMIIBO_PRICE_INDEX_FLUSH_INTERVAL", "50")), 1
        )

        def flush_latest_index():
            nonlocal index_failed, pending_index_prices
            if not save or not pending_index_prices:
                return
            try:
                repository.save_latest_index(pending_index_prices, self.today)
            except Exception as exc:
                index_failed += 1
                logger.warning(
                    "amiibo-price-index-save-failed | count=%s error=%s",
                    len(pending_index_prices),
                    exc,
                )
            finally:
                pending_index_prices = {}

        for amiibo in amiibos:
            if limit is not None and processed >= limit:
                break

            price_id = amiibo_price_id(amiibo)
            if not price_id:
                continue

            processed += 1
            if save and pricing_snapshot_is_current(
                current_price_map.get(price_id), self.today
            ):
                already_current += 1
                continue

            try:
                items = self.ebay_client.search_amiibo(amiibo)
                pricing = estimate_prices_from_ebay_items(amiibo, items)
                pricing["source_url"] = build_ebay_search_url(amiibo)
                if save:
                    repository.save_snapshot(price_id, pricing, self.today)
                    try:
                        repository.prune_old_snapshots(price_id, cutoff_date)
                    except Exception as exc:
                        logger.warning(
                            "amiibo-price-prune-failed | id=%s error=%s",
                            price_id,
                            exc,
                        )
                updated_prices[price_id] = pricing
                pending_index_prices[price_id] = pricing
                updated += 1
                if pricing.get("sample_count", 0) > 0 or any(
                    pricing.get(field) is not None
                    for field in ("loose_estimate_cents", "new_estimate_cents")
                ):
                    priced += 1
                else:
                    unavailable += 1
                if len(pending_index_prices) >= index_flush_interval:
                    flush_latest_index()
            except Exception as exc:
                failed += 1
                errors.append({"amiibo_id": price_id, "error": str(exc)[:200]})
                logger.warning(
                    "amiibo-price-refresh-failed | id=%s error=%s", price_id, exc
                )

        flush_latest_index()

        result = {
            "status": "ok" if failed == 0 and index_failed == 0 else "partial",
            "dry_run": not save,
            "environment": environment,
            "processed": processed,
            "updated": updated,
            "priced": priced,
            "unavailable": unavailable,
            "already_current": already_current,
            "failed": failed,
            "index_failed": index_failed,
            "errors": errors[:10],
        }
        self._log_result(result, started_at, runtime_config)
        return result
