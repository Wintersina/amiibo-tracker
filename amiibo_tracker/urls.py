from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from tracker.sitemap_views import sitemap
from tracker.sitemaps import StaticViewSitemap, BlogPostSitemap

# Individual amiibo detail pages are intentionally excluded: they are thin,
# templated pages now served with `noindex`, so listing them in the sitemap
# would send Google conflicting signals. See AmiiboSitemap (kept for reference).
sitemaps = {
    'static': StaticViewSitemap,
    'blog': BlogPostSitemap,
}

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/images/favicon.png", permanent=True),
    ),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path("", include("tracker.urls")),
]
