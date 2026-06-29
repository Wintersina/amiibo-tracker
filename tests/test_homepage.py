from django.test import Client, override_settings

from tracker import pricing, views


def homepage_post(slug, title, date):
    return {
        "slug": slug,
        "title": title,
        "date": date,
        "excerpt": f"{title} excerpt",
        "featured_image": "",
        "author": "sina",
    }


def homepage_amiibo(name, tail):
    return {
        "name": name,
        "amiiboSeries": "Super Smash Bros.",
        "gameSeries": "Super Mario",
        "type": "Figure",
        "head": "00000000",
        "tail": tail,
        "image": "",
    }


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_homepage_renders_three_latest_blog_posts(monkeypatch):
    monkeypatch.setattr(views.IndexView, "_fetch_local_amiibos", lambda self: [])
    monkeypatch.setattr(
        views,
        "load_blog_posts",
        lambda: [
            homepage_post("oldest", "Oldest Guide", "2026-01-01"),
            homepage_post("newest", "Newest Guide", "2026-06-29"),
            homepage_post("middle", "Middle Guide", "2026-03-10"),
            homepage_post("fourth", "Fourth Guide", "2026-02-01"),
        ],
    )

    response = Client().get("/")
    body = response.content.decode()

    assert response.status_code == 200
    assert body.count('data-track="home-guide-card"') == 3
    assert "Newest Guide" in body
    assert "Middle Guide" in body
    assert "Fourth Guide" in body
    assert "Oldest Guide" not in body


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_homepage_top_prices_use_current_pricing_order(monkeypatch):
    amiibos = [
        homepage_amiibo("Highest NIB", "00000001"),
        homepage_amiibo("Highest Loose", "00000002"),
        homepage_amiibo("Third Price", "00000003"),
        homepage_amiibo("Fourth Price", "00000004"),
        homepage_amiibo("Fifth Price", "00000005"),
        homepage_amiibo("Sixth Price", "00000006"),
        homepage_amiibo("Seventh Price", "00000007"),
        homepage_amiibo("Eighth Price", "00000008"),
        homepage_amiibo("Ninth Price", "00000009"),
    ]
    price_map = {
        "Highest NIB": (1200, 9000),
        "Highest Loose": (8600, None),
        "Third Price": (3000, 7600),
        "Fourth Price": (6500, None),
        "Fifth Price": (5400, 4000),
        "Sixth Price": (1000, 5000),
        "Seventh Price": (4900, None),
        "Eighth Price": (4400, None),
        "Ninth Price": (3900, None),
    }

    def fake_enrich(enriched_amiibos):
        for amiibo in enriched_amiibos:
            loose_cents, new_cents = price_map[amiibo["name"]]
            amiibo["pricing"] = pricing.normalize_pricing_for_display(
                amiibo,
                {
                    "currency": "USD",
                    "loose_estimate_cents": loose_cents,
                    "new_estimate_cents": new_cents,
                    "sample_count": 5,
                    "confidence": "medium",
                    "snapshot_date": "2026-06-29",
                },
            )

    monkeypatch.setattr(views.IndexView, "_fetch_local_amiibos", lambda self: amiibos)
    monkeypatch.setattr(views, "enrich_amiibos_with_pricing", fake_enrich)
    monkeypatch.setattr(views, "load_blog_posts", lambda: [])

    first_response = Client().get("/")
    first_body = first_response.content.decode()

    assert first_response.status_code == 200
    assert first_body.count('class="price-card"') == 5
    assert "Sixth Price" not in first_body
    assert "Eighth Price" not in first_body
    assert "Ninth Price" not in first_body
    assert "Open AmiiboDex" not in first_body
    assert first_body.index("Highest NIB") < first_body.index("Highest Loose")
    assert "NIB estimate" in first_body
    assert "Loose estimate" in first_body

    price_map["Highest Loose"] = (9500, None)

    second_response = Client().get("/")
    second_body = second_response.content.decode()

    assert second_response.status_code == 200
    assert second_body.count('class="price-card"') == 5
    assert second_body.index("Highest Loose") < second_body.index("Highest NIB")
