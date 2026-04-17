import pathlib
import sys
import os

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set Django settings module for tests before importing anything Django-related
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "amiibo_tracker.settings.testing")

import django
from django.conf import settings

# Initialize Django for tests
django.setup()

from tracker.google_sheet_client_manager import GoogleSheetClientManager


@pytest.fixture(scope="session", autouse=True)
def configure_settings():
    """Ensure Django is configured with testing settings."""
    return settings


@pytest.fixture(autouse=True)
def clear_caches():
    # GoogleSheetConfigManager's cache is per-instance (see service_domain.py),
    # so test isolation there happens naturally when each test builds a fresh
    # manager. Only the still-class-level GoogleSheetClientManager caches need
    # explicit reset between tests.
    GoogleSheetClientManager._spreadsheet_cache.clear()
    GoogleSheetClientManager._worksheet_cache.clear()
    yield
    GoogleSheetClientManager._spreadsheet_cache.clear()
    GoogleSheetClientManager._worksheet_cache.clear()
