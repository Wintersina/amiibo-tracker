from django.urls import path

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
)

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
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
]
