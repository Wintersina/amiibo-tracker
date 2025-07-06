from .base import *
import os

os.environ["ENV_NAME"] = "production"
DEBUG = False

ALLOWED_HOSTS = ["yourproductiondomain.com", "www.yourproductiondomain.com"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": "your_prod_db_name",
        "USER": "your_prod_db_user",
        "PASSWORD": "your_prod_db_password",
        "HOST": "your_prod_db_host",
        "PORT": "",
    }
}

STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "mediafiles"


SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = True
