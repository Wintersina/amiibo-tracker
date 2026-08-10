"""Covers the shared collection controls and the sponsorship CTA.

The tracker page needs a live Google Sheets session, so the shared partial is
exercised two ways: end-to-end through /demo/, and directly through the template
engine for the server-rendered type chips only the tracker passes in.
"""

from django.template.loader import render_to_string
from django.test import Client, override_settings

from tracker import context_processors, views


DOCK_MARKUP = [
    'id="collectionControls"',
    'id="dockBackdrop"',
    'id="hamburgerToggle"',
    'id="collectionSheet"',
    'id="collectionTotal"',
]


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_demo_page_ships_the_bottom_dock_and_its_shared_assets():
    body = Client().get("/demo/").content.decode()

    for marker in DOCK_MARKUP:
        assert marker in body, marker

    assert "css/collection-controls.css" in body
    assert "js/collection-dock.js" in body
    # The hamburger drives the sheet, so the two must stay wired together.
    assert 'aria-controls="collectionSheet"' in body
    assert 'aria-expanded="false"' in body
    # The old inline toggle is gone; nothing should look up the dead id.
    assert "getElementById('mobileMenu')" not in body


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_demo_page_no_longer_carries_duplicated_control_css():
    body = Client().get("/demo/").content.decode()

    assert ".top-controls {" not in body
    assert ".type-chip {" not in body


def test_shared_controls_render_server_side_type_chips():
    html = render_to_string(
        "tracker/_collection_controls.html",
        {
            "welcome_name": "Sina",
            "amiibo_types": [
                {"name": "Figure", "ignored": False},
                {"name": "Card", "ignored": True},
            ],
            "dark_toggle_sheet_action": True,
        },
    )

    assert "Welcome, Sina." in html
    assert (
        '<input type="checkbox" data-type="Figure" data-sheet-action checked>' in html
    )
    assert '<input type="checkbox" data-type="Card" data-sheet-action >' in html
    # The theme toggle text is swapped through a dedicated span so the label
    # survives; the page scripts write to #darkModeIcon, not the button.
    assert 'id="darkModeIcon"' in html


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_homepage_shows_support_cta_alongside_the_guides(monkeypatch):
    monkeypatch.setattr(views.IndexView, "_fetch_local_amiibos", lambda self: [])
    monkeypatch.setattr(views, "load_blog_posts", lambda: [])

    body = Client().get("/").content.decode()

    assert 'data-track="home-support"' in body
    assert context_processors.DEFAULT_SUPPORT_URL in body
    assert 'rel="noopener noreferrer"' in body
    # "Buy me a coffee" was rejected as wording; keep it from creeping back.
    assert "coffee" not in body.lower()


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_support_link_appears_in_the_global_nav_on_every_page():
    client = Client()

    for path in ("/", "/about/", "/privacy/", "/demo/"):
        body = client.get(path).content.decode()
        assert 'data-track="nav-support"' in body, path
        assert 'data-track="mobile-nav-support"' in body, path


def test_support_url_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("SUPPORT_URL", "https://example.test/tip")

    assert context_processors.support_links(None) == {
        "support_url": "https://example.test/tip"
    }


def test_support_url_falls_back_when_environment_is_blank(monkeypatch):
    monkeypatch.setenv("SUPPORT_URL", "")

    assert context_processors.support_links(None) == {
        "support_url": context_processors.DEFAULT_SUPPORT_URL
    }
