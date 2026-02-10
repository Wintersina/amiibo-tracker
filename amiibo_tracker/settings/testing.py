"""
Django settings for testing environment.
Inherits from base settings and overrides for test execution.
"""

from .base import *

# Use a fast, in-memory database for tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Use a fixed secret key for tests
SECRET_KEY = "test-secret-key-for-testing-only-not-for-production"

# Debug should be False in tests to catch issues that would occur in production
DEBUG = False

# Allow all hosts in tests
ALLOWED_HOSTS = ["*"]

# Use signed cookies for sessions in tests (no database required)
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

# Disable migrations for faster test execution
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Use in-memory cache for tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

# Use simple static files storage for tests (no manifest, no compression)
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }
}

# Simplify password hashing for faster tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Disable logging during tests (optional - uncomment to reduce test output)
# LOGGING = {
#     "version": 1,
#     "disable_existing_loggers": True,
#     "handlers": {
#         "null": {
#             "class": "logging.NullHandler",
#         },
#     },
#     "root": {
#         "handlers": ["null"],
#         "level": "CRITICAL",
#     },
# }
