from django.core.exceptions import ImproperlyConfigured

from .base import *
import os


# Determine environment and import specific settings
ENV = os.getenv("ENV_NAME", "development")  # Default to 'development' if not set

if ENV == "production":
    from .production import *
elif ENV == "development":
    from .development import *
# You can add more elif for 'staging', 'testing', etc.
else:
    raise ImproperlyConfigured(
        f"Unknown ENV_NAME: {ENV}. Must be 'development' or 'production'."
    )

try:
    from .local_settings import *
except ImportError:
    pass
