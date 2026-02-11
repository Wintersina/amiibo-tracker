from django.urls import path
from django.views.generic import TemplateView

from tracker.views import (
    IndexView,
    AmiiboListView,
    ToggleDarkModeView,
    ToggleTypeFilterView,
    OAuthView,
    OAuthCallbackView,
    LogoutView,
    ToggleCollectedView,
    PrivacyPolicyView,
    AmiiboDatabaseView,
    DemoView,
    BlogListView,
    BlogPostView,
    AmiibodexView,
    AmiiboDetailView,
    RobotsTxtView,
)

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
    path("robots.txt", RobotsTxtView.as_view(), name="robots"),
    path(
        "about/", TemplateView.as_view(template_name="tracker/about.html"), name="about"
    ),
    path("demo/", DemoView.as_view(), name="demo"),
    path("tracker/", AmiiboListView.as_view(), name="amiibo_list"),
    path("toggle/", ToggleCollectedView.as_view(), name="toggle_collected"),
    path("toggle-dark-mode/", ToggleDarkModeView.as_view(), name="toggle_dark_mode"),
    path(
        "toggle-type-filter/",
        ToggleTypeFilterView.as_view(),
        name="toggle_type_filter",
    ),
    path("oauth-login/", OAuthView.as_view(), name="oauth_login"),
    path("oauth2callback/", OAuthCallbackView.as_view(), name="oauth2callback"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("privacy/", PrivacyPolicyView.as_view(), name="privacy"),
    path("api/amiibo/", AmiiboDatabaseView.as_view(), name="amiibo_database"),
    path("amiibodex/", AmiibodexView.as_view(), name="amiibodex"),
    path("blog/", BlogListView.as_view(), name="blog_list"),
    path(
        "blog/number-released/amiibo/<str:amiibo_id>/",
        AmiiboDetailView.as_view(),
        name="amiibo_detail",
    ),
    path("blog/<slug:slug>/", BlogPostView.as_view(), name="blog_post"),
]
