from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from tracker.sitemap_views import sitemap
from tracker.sitemaps import (
    StaticViewSitemap,
    AuthorSitemap,
    BlogPostSitemap,
)

# Amiibo detail pages are deliberately absent: their templated ~50-word
# descriptions tripped AdSense's "low value content" review (June 2026), so
# they are served with `noindex, follow` and must not be advertised to
# crawlers here. Re-add AmiiboSitemap only for pages enriched with
# substantial unique content, and flip their robots meta in lockstep.
sitemaps = {
    "static": StaticViewSitemap,
    "authors": AuthorSitemap,
    "blog": BlogPostSitemap,
}

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/images/favicon.png", permanent=True),
    ),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("", include("tracker.urls")),
]
