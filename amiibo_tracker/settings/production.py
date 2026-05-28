import os

import dj_database_url

from .base import *  # noqa: F401,F403

os.environ["ENV_NAME"] = "production"
DEBUG = False

ALLOWED_HOSTS = ALLOWED_HOSTS or ["goozamiibo.com"]

default_db_path = os.environ.get("DJANGO_SQLITE_PATH", "/tmp/db.sqlite3")

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{default_db_path}", conn_max_age=600
    )
}

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# Accept HTTPS POSTs from the production hosts so Django's CSRF middleware
# works when the app is served on custom domains (required for OAuth callbacks
# and authenticated form submissions).
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS or [
    f"https://{host}"
    for host in ALLOWED_HOSTS
    if host not in {"*", "localhost"}
]

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
# Cloud Run terminates TLS before forwarding requests to the container. Rely on
# the platform to handle HTTPS enforcement unless explicitly overridden so the
# app can return a 200 on custom domains without triggering an extra redirect.
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER or "noreply@goozamiibo.com"

DAILY_REPORT_TO_EMAIL = os.environ.get("DAILY_REPORT_TO_EMAIL", "")
DAILY_REPORT_SCHEDULER_SA_EMAIL = os.environ.get(
    "DAILY_REPORT_SCHEDULER_SA_EMAIL", ""
)
GCS_REPORTS_BUCKET = os.environ.get("GCS_REPORTS_BUCKET", "")

LOKI_QUERY_URL = os.environ.get("LOKI_QUERY_URL") or os.environ.get("LOKI_URL", "")
LOKI_QUERY_USER = os.environ.get("LOKI_QUERY_USER") or os.environ.get("LOKI_USER", "")
LOKI_QUERY_API_KEY = os.environ.get("LOKI_QUERY_API_KEY") or os.environ.get(
    "LOKI_API_KEY", ""
)
