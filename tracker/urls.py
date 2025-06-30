from django.urls import path
from . import views

urlpatterns = [
    path("", views.amiibo_list, name="amiibo_list"),
    path("toggle/", views.toggle_collected, name="toggle_collected"),
    path("toggle-dark-mode/", views.toggle_dark_mode, name="toggle_dark_mode"),
    path("oauth-login/", views.oauth_login, name="oauth_login"),
    path("oauth2callback/", views.oauth2callback, name="oauth2callback"),
]
