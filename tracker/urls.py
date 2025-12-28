from django.urls import path

from tracker.views import (
    IndexView,
    AmiiboListView,
    ToggleDarkModeView,
    OAuthView,
    OAuthCallbackView,
    LogoutView,
    ToggleCollectedView,
)

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
    path("tracker/", AmiiboListView.as_view(), name="amiibo_list"),
    path("toggle/", ToggleCollectedView.as_view(), name="toggle_collected"),
    path("toggle-dark-mode/", ToggleDarkModeView.as_view(), name="toggle_dark_mode"),
    path("oauth-login/", OAuthView.as_view(), name="oauth_login"),
    path("oauth2callback/", OAuthCallbackView.as_view(), name="oauth2callback"),
    # Support legacy/allauth-style callback URIs that may still be configured in Google OAuth
    # settings by routing them to the same OAuth callback view used by the app.
    path(
        "accounts/google/login/callback/",
        OAuthCallbackView.as_view(),
        name="oauth2callback_compat",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
]
