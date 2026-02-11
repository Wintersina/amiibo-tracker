from pathlib import Path
import os
import logging

BASE_DIR = Path(__file__).resolve().parent.parent.parent

STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-default-key")
DEBUG = os.environ.get("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "amiibo_tracker.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "amiibo_tracker.wsgi.application"

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

DATABASES = {
    "default": {
        # Default to Django's dummy backend so the app does not try to create or
        # write to a local SQLite file in environments where persistence is
        # ephemeral (e.g., Cloud Run). If a database is needed for local
        # development or future features, set DJANGO_DB_ENGINE to a real backend
        # such as "django.db.backends.sqlite3".
        "ENGINE": os.environ.get(
            "DJANGO_DB_ENGINE", "django.db.backends.dummy"
        ),
        "NAME": os.environ.get("DJANGO_DB_NAME", "dummy"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-sheets-api-cache",
    }
}

# By default Django stores session data in the database (the `django_session`
# table). In environments where the database may not be writable or may be
# reset between deploys (e.g., Cloud Run), store sessions in signed cookies so
# we do not rely on any database tables being present.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": True,
        },
        "googleapiclient": {"level": "WARNING"},
        "google.auth": {"level": "WARNING"},
        "google.auth.transport.requests": {"level": "WARNING"},
        "oauthlib": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "gspread": {"level": "WARNING"},
    },
}
