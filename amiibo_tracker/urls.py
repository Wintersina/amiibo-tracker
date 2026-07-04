from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from tracker.sitemap_views import sitemap
from tracker.sitemaps import (
    StaticViewSitemap,
    AuthorSitemap,
    BlogPostSitemap,
    AmiiboSitemap,
)

# Amiibo detail pages are now content-rich (pricing, related figures, FAQ) and
# served with `index, follow`, so they belong in the sitemap. Listing them here
# gives Google an authoritative crawl list with fresh lastmod signals, matching
# the indexable meta on the pages themselves.
sitemaps = {
    "static": StaticViewSitemap,
    "authors": AuthorSitemap,
    "blog": BlogPostSitemap,
    "amiibo": AmiiboSitemap,
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
