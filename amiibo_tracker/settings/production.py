import os

import dj_database_url

from .base import *  # noqa: F401,F403

os.environ["ENV_NAME"] = "production"
DEBUG = False

ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost"]

default_db_path = os.environ.get("DJANGO_SQLITE_PATH", "/tmp/db.sqlite3")

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{default_db_path}", conn_max_age=600
    )
}

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "mediafiles"

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
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
