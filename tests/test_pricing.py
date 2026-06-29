import json
from datetime import date

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, override_settings

from tracker import pricing, views


@pytest.fixture(autouse=True)
def isolate_local_price_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AMIIBO_PRICE_LOCAL_CACHE_PATH", str(tmp_path / "amiibo_price_cache.local.json")
    )
    monkeypatch.delenv("AMIIBO_PRICE_USE_LOCAL_CACHE", raising=False)


def mario_amiibo():
    return {
        "name": "Mario",
        "amiiboSeries": "Super Smash Bros.",
        "gameSeries": "Super Mario",
        "type": "Figure",
        "head": "00000000",
        "tail": "00000001",
    }


def ebay_item(title, value, condition="Used", shipping="0.00"):
    return {
        "title": title,
        "condition": condition,
        "price": {"value": value, "currency": "USD"},
        "shippingOptions": [{"shippingCost": {"value": shipping}}],
    }


def test_estimate_prices_from_ebay_items_filters_and_buckets_results():
    items = [
        ebay_item("Mario amiibo Super Smash Bros loose", "15.00", "Used", "4.00"),
        ebay_item("Nintendo Mario amiibo OOB", "17.00", "Used"),
        ebay_item("Mario amiibo new in box sealed", "45.00", "New"),
        ebay_item("Mario amiibo NIB", "55.00", "New"),
        ebay_item("Mario amiibo NFC card", "3.00", "New"),
        ebay_item("Mario amiibo lot bundle", "100.00", "Used"),
    ]

    result = pricing.estimate_prices_from_ebay_items(mario_amiibo(), items)

    assert result["loose_estimate_cents"] == 1800
    assert result["new_estimate_cents"] == 5000
    assert result["sample_count"] == 4
    assert result["confidence"] == "medium"


def test_amiibo_card_rows_allow_card_listing_titles():
    amiibo = {
        **mario_amiibo(),
        "name": "Isabelle",
        "amiiboSeries": "Animal Crossing Cards Series 1",
        "type": "Card",
    }
    items = [
        ebay_item("Isabelle amiibo card Animal Crossing authentic", "8.00", "Used"),
    ]

    result = pricing.estimate_prices_from_ebay_items(amiibo, items)

    assert result["loose_estimate_cents"] == 800
    assert result["sample_count"] == 1


def test_normalize_pricing_for_display_falls_back_to_ebay_listing_link():
    display = pricing.normalize_pricing_for_display(mario_amiibo(), None)

    assert display["has_estimate"] is False
    assert display["display"] == "Check eBay"
    assert "ebay.com" in display["source_url"]
    assert "Mario" in display["source_url"]


def test_build_price_chart_data_creates_svg_points_and_recent_rows():
    display = pricing.normalize_pricing_for_display(
        mario_amiibo(),
        {
            "currency": "USD",
            "loose_estimate_cents": 2200,
            "new_estimate_cents": 5600,
            "sample_count": 8,
            "confidence": "high",
            "snapshot_date": "2026-06-03",
        },
    )
    history = [
        {
            "snapshot_date": "2026-06-01",
            "currency": "USD",
            "loose_estimate_cents": 1800,
            "new_estimate_cents": 5000,
        },
        {
            "snapshot_date": "2026-06-02",
            "currency": "USD",
            "loose_estimate_cents": 2000,
            "new_estimate_cents": 5400,
        },
        {
            "snapshot_date": "2026-06-03",
            "currency": "USD",
            "loose_estimate_cents": 2200,
            "new_estimate_cents": 5600,
        },
    ]

    chart = pricing.build_price_chart_data(display, history)

    assert chart["has_chart"] is True
    assert chart["has_loose_line"] is True
    assert chart["has_new_line"] is True
    assert len(chart["loose_polyline"].split()) == 3
    assert chart["loose_change"] == "+22%"
    assert chart["new_change"] == "+12%"
    assert chart["recent_points"][0]["label"] == "Jun 3"


def test_enrich_skips_firestore_reads_in_development(monkeypatch):
    class FailingRepository:
        def __init__(self):
            raise AssertionError("repository should not be initialized")

    monkeypatch.setenv("ENV_NAME", "development")
    monkeypatch.delenv("AMIIBO_PRICE_ENABLE_LOCAL_READS", raising=False)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.setattr(pricing, "AmiiboPricingRepository", FailingRepository)

    amiibos = [mario_amiibo()]
    pricing.enrich_amiibos_with_pricing(amiibos)

    assert amiibos[0]["pricing"]["has_estimate"] is False
    assert "ebay.com" in amiibos[0]["pricing"]["source_url"]


def test_price_refresh_service_skips_without_ebay_credentials():
    class UnconfiguredEbayClient:
        configured = False

    result = pricing.AmiiboPriceRefreshService(
        ebay_client=UnconfiguredEbayClient(),
        repository=object(),
        today=date(2026, 6, 28),
    ).refresh([mario_amiibo()])

    assert result["status"] == "skipped"
    assert result["reason"] == "ebay_credentials_missing"


def test_ebay_config_supports_sandbox_environment(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "sandbox-client-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "sandbox-client-secret")
    monkeypatch.setenv("EBAY_ENV", "sandbox")

    config = pricing.EbayConfig.from_env()

    assert config.environment == "sandbox"
    assert config.token_url.startswith("https://api.sandbox.ebay.com/")
    assert config.browse_search_url.startswith("https://api.sandbox.ebay.com/")


def test_price_refresh_dry_run_does_not_require_repository():
    class Config:
        environment = "sandbox"

    class ConfiguredEbayClient:
        configured = True
        config = Config()

        def search_amiibo(self, amiibo):
            return [ebay_item("Mario amiibo loose", "15.00", "Used")]

    result = pricing.AmiiboPriceRefreshService(
        ebay_client=ConfiguredEbayClient(),
        repository=None,
        today=date(2026, 6, 28),
    ).refresh([mario_amiibo()], save=False)

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["environment"] == "sandbox"
    assert result["updated"] == 1


def test_price_refresh_skips_when_firestore_credentials_missing(monkeypatch):
    class Config:
        environment = "production"

    class ConfiguredEbayClient:
        configured = True
        config = Config()

    class MissingCredentialsRepository:
        def __init__(self):
            raise pricing.DefaultCredentialsError("missing adc")

    monkeypatch.setattr(
        pricing, "AmiiboPricingRepository", MissingCredentialsRepository
    )

    result = pricing.AmiiboPriceRefreshService(
        ebay_client=ConfiguredEbayClient(),
        repository=None,
        today=date(2026, 6, 28),
    ).refresh([mario_amiibo()])

    assert result["status"] == "skipped"
    assert result["reason"] == "firestore_credentials_missing"


def test_price_refresh_skips_once_when_ebay_auth_fails():
    class Config:
        environment = "production"

    class AuthFailingEbayClient:
        configured = True
        config = Config()

        def __init__(self):
            self.auth_calls = 0
            self.search_calls = 0

        def ensure_authenticated(self):
            self.auth_calls += 1
            raise pricing.EbayAuthenticationError("bad credentials")

        def search_amiibo(self, amiibo):
            self.search_calls += 1
            return []

    ebay_client = AuthFailingEbayClient()
    result = pricing.AmiiboPriceRefreshService(
        ebay_client=ebay_client,
        repository=None,
        today=date(2026, 6, 28),
    ).refresh([mario_amiibo()], save=False)

    assert result["status"] == "skipped"
    assert result["reason"] == "ebay_auth_failed"
    assert result["environment"] == "production"
    assert ebay_client.auth_calls == 1
    assert ebay_client.search_calls == 0


def test_repository_reads_latest_prices_from_index():
    class FakeDocument:
        exists = True

        def __init__(self, payload=None, doc_id="latest"):
            self.payload = payload or {}
            self.id = doc_id

        def to_dict(self):
            return self.payload

        def get(self):
            return self

    class FakeCollection:
        def document(self, doc_id):
            return FakeDocument(
                {
                    "prices": {
                        "00000000-00000001": {
                            "loose_estimate_cents": 1800,
                            "currency": "USD",
                        }
                    }
                },
                doc_id=doc_id,
            )

    class FakeClient:
        def collection(self, name):
            assert name == pricing.AMIIBO_PRICE_INDEX_COLLECTION
            return FakeCollection()

        def get_all(self, doc_refs):
            raise AssertionError("fallback reads should not be needed")

    result = pricing.AmiiboPricingRepository(FakeClient()).get_latest_map(
        ["00000000-00000001"]
    )

    assert result["00000000-00000001"]["loose_estimate_cents"] == 1800


def test_repository_skips_large_latest_doc_fallback(monkeypatch):
    class MissingDocument:
        exists = False

        def get(self):
            return self

    class FakeCollection:
        def document(self, doc_id):
            return MissingDocument()

    class FakeClient:
        def collection(self, name):
            return FakeCollection()

        def get_all(self, doc_refs):
            raise AssertionError("large fallback reads should be skipped")

    monkeypatch.delenv("AMIIBO_PRICE_DOC_FALLBACK_LIMIT", raising=False)

    result = pricing.AmiiboPricingRepository(FakeClient()).get_latest_map(
        [f"head-tail-{index}" for index in range(51)]
    )

    assert result == {}


def test_local_pricing_repository_persists_latest_and_history(tmp_path):
    cache_path = tmp_path / "price-cache.local.json"
    repository = pricing.LocalAmiiboPricingRepository(cache_path)
    item_pricing = {
        "currency": "USD",
        "loose_estimate_cents": 1800,
        "new_estimate_cents": 5000,
        "sample_count": 6,
        "confidence": "medium",
    }

    repository.save_snapshot("00000000-00000001", item_pricing, date(2026, 6, 29))

    latest = repository.get_latest_map(["00000000-00000001"])
    history = repository.get_history("00000000-00000001")

    assert latest["00000000-00000001"]["loose_estimate_cents"] == 1800
    assert history[0]["snapshot_date"] == "2026-06-29"


def test_local_price_cache_auto_enabled_in_development_when_file_exists(
    monkeypatch, tmp_path
):
    cache_path = tmp_path / "price-cache.local.json"
    cache_path.write_text('{"prices": {}, "history": {}}\n', encoding="utf-8")

    monkeypatch.setenv("ENV_NAME", "development")
    monkeypatch.delenv("AMIIBO_PRICE_USE_LOCAL_CACHE", raising=False)
    monkeypatch.setenv("AMIIBO_PRICE_LOCAL_CACHE_PATH", str(cache_path))

    assert pricing.local_price_cache_enabled() is True
    assert isinstance(
        pricing.get_pricing_repository(), pricing.LocalAmiiboPricingRepository
    )


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_amiibodex_reads_prices_from_local_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "price-cache.local.json"
    cache_path.write_text(
        json.dumps(
            {
                "prices": {
                    "00000000-00000001": {
                        "amiibo_id": "00000000-00000001",
                        "currency": "USD",
                        "loose_estimate_cents": 1800,
                        "new_estimate_cents": 5000,
                        "sample_count": 6,
                        "confidence": "medium",
                        "source_label": "eBay active listings",
                        "source_url": (
                            "https://www.ebay.com/sch/i.html?_nkw=Mario+amiibo"
                        ),
                        "snapshot_date": "2026-06-29",
                    }
                },
                "history": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    amiibo = {
        **mario_amiibo(),
        "release": {"na": "2014-11-21"},
        "image": "",
    }

    monkeypatch.setenv("ENV_NAME", "development")
    monkeypatch.setenv("AMIIBO_PRICE_LOCAL_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        views.AmiibodexView,
        "_fetch_local_amiibos",
        lambda self: [amiibo],
    )

    response = Client().get("/amiibodex/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Loose $18 / NIB $50" in body
    assert "medium confidence" in body
    assert "View eBay listings" in body


def test_price_refresh_writes_latest_index_after_updates():
    class ConfiguredEbayClient:
        configured = True

        def search_amiibo(self, amiibo):
            return [ebay_item("Mario amiibo loose", "15.00", "Used")]

    class FakeRepository:
        def __init__(self):
            self.index = None

        def save_snapshot(self, amiibo_id, item_pricing, snapshot_date):
            assert amiibo_id == "00000000-00000001"

        def prune_old_snapshots(self, amiibo_id, before_date):
            return 0

        def save_latest_index(self, pricing_by_id, snapshot_date):
            self.index = pricing_by_id

    repository = FakeRepository()
    result = pricing.AmiiboPriceRefreshService(
        ebay_client=ConfiguredEbayClient(),
        repository=repository,
        today=date(2026, 6, 28),
    ).refresh([mario_amiibo()])

    assert result["status"] == "ok"
    assert repository.index["00000000-00000001"]["loose_estimate_cents"] == 1500


def test_refresh_command_skips_without_ebay_credentials(monkeypatch, capsys):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    call_command("refresh_amiibo_prices", limit=1)

    captured = capsys.readouterr()
    assert "Skipped: ebay_credentials_missing" in captured.out


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_price_refresh_api_returns_unhealthy_status_when_skipped(monkeypatch):
    class SkippedRefreshService:
        def refresh(self, amiibos):
            return {
                "status": "skipped",
                "reason": "ebay_credentials_missing",
                "environment": "production",
                "processed": 0,
                "updated": 0,
                "priced": 0,
                "unavailable": 0,
                "failed": 0,
            }

    cache.clear()
    monkeypatch.setattr(
        views.PriceRefreshAPIView,
        "_fetch_local_amiibos",
        lambda self: [mario_amiibo()],
    )
    monkeypatch.setattr(pricing, "AmiiboPriceRefreshService", SkippedRefreshService)

    response = Client().post("/api/refresh-prices/")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "skipped"
    assert payload["reason"] == "ebay_credentials_missing"


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_amiibodex_renders_cached_price(monkeypatch):
    amiibo = {
        **mario_amiibo(),
        "release": {"na": "2014-11-21"},
        "image": "",
    }

    monkeypatch.setattr(
        views.AmiibodexView,
        "_fetch_local_amiibos",
        lambda self: [amiibo],
    )

    def fake_enrich(amiibos):
        amiibos[0]["pricing"] = pricing.normalize_pricing_for_display(
            amiibos[0],
            {
                "currency": "USD",
                "loose_estimate_cents": 1800,
                "new_estimate_cents": 5000,
                "sample_count": 6,
                "confidence": "medium",
                "source_label": "eBay active listings",
                "source_url": "https://www.ebay.com/sch/i.html?_nkw=Mario+amiibo",
                "snapshot_date": "2026-06-28",
            },
        )

    monkeypatch.setattr(views, "enrich_amiibos_with_pricing", fake_enrich)

    response = Client().get("/amiibodex/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Loose $18 / NIB $50" in body
    assert "medium confidence" in body
    assert "View eBay listings" in body
