from django.test import Client, override_settings

from tracker import views


ADSENSE_SCRIPT = "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"
ADSENSE_ACCOUNT = 'meta name="google-adsense-account" content="ca-pub-6947554333794592"'


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_adsense_script_only_loads_on_eligible_public_content_pages(monkeypatch):
    monkeypatch.setattr(views.IndexView, "_fetch_local_amiibos", lambda self: [])
    monkeypatch.setattr(views, "load_blog_posts", lambda: [])

    client = Client()

    homepage = client.get("/").content.decode()
    about = client.get("/about/").content.decode()
    privacy = client.get("/privacy/").content.decode()
    demo = client.get("/demo/").content.decode()

    assert ADSENSE_ACCOUNT in homepage
    assert ADSENSE_SCRIPT in homepage
    assert ADSENSE_SCRIPT in about
    assert ADSENSE_SCRIPT not in privacy
    assert ADSENSE_SCRIPT not in demo


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_privacy_policy_discloses_ad_and_diagnostics_providers():
    body = Client().get("/privacy/").content.decode()

    assert "Advertising &amp; Cookies" in body
    assert "Google-served ads" in body
    assert "use web beacons" in body
    assert "Analytics &amp; Diagnostics" in body
