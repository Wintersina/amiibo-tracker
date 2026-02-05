from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/images/favicon.png", permanent=True),
    ),
    path("", include("tracker.urls")),
]
