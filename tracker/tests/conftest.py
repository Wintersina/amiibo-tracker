"""
Test configuration for tracker tests.
"""

import os
import sys
import pathlib
import django
import pytest
from django.conf import settings

# Add project root to path
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configure Django settings for tests
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "amiibo_tracker.settings.testing")

# Initialize Django
if not settings.configured:
    django.setup()


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    # The rate limiter (check_rate_limit) keeps its counters in the Django
    # cache. LocMemCache is per-process, so without resetting between tests the
    # counts bleed and later requests get rejected with HTTP 429.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
