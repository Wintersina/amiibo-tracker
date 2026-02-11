from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from tracker.sitemap_views import sitemap
from tracker.sitemaps import StaticViewSitemap, BlogPostSitemap, AmiiboSitemap

sitemaps = {
    'static': StaticViewSitemap,
    'blog': BlogPostSitemap,
    'amiibo': AmiiboSitemap,
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
