import pathlib
import sys

import pytest
from django.conf import settings


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.service_domain import GoogleSheetConfigManager


@pytest.fixture(scope="session", autouse=True)
def configure_settings(tmp_path_factory):
    if not settings.configured:
        settings.configure(BASE_DIR=str(tmp_path_factory.mktemp("base")))
    return settings


@pytest.fixture(autouse=True)
def clear_caches():
    GoogleSheetClientManager._spreadsheet_cache.clear()
    GoogleSheetClientManager._worksheet_cache.clear()
    GoogleSheetConfigManager._CONFIG_CACHE.clear()
    yield
    GoogleSheetClientManager._spreadsheet_cache.clear()
    GoogleSheetClientManager._worksheet_cache.clear()
    GoogleSheetConfigManager._CONFIG_CACHE.clear()
