"""Pin the noindex posture adopted after the June 2026 AdSense
"low value content" flag: templated amiibo detail pages stay out of the
sitemap and carry a noindex robots meta. If you re-index them, do it per
enriched page and update these expectations deliberately.
"""

import re

from django.test import Client, override_settings


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_sitemap_excludes_amiibo_detail_pages():
    response = Client().get("/sitemap.xml")

    assert response.status_code == 200
    urls = re.findall(r"<loc>(.*?)</loc>", response.content.decode())
    assert urls, "sitemap should still list static/blog/author pages"
    assert not [url for url in urls if "/blog/number-released/amiibo/" in url]


@override_settings(ALLOWED_HOSTS=["testserver", "goozamiibo.com"])
def test_amiibo_detail_page_is_noindex():
    # 8-Bit Mario Classic Color, a stable long-released figure.
    response = Client().get("/blog/number-released/amiibo/00000000-00340102/")

    assert response.status_code == 200
    match = re.search(
        r'<meta name="robots" content="([^"]*)"', response.content.decode()
    )
    assert match, "amiibo detail page must declare a robots meta tag"
    assert "noindex" in match.group(1)
