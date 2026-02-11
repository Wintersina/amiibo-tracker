"""
Tests for Nintendo scraper API endpoint.
"""
import json
import pytest
from unittest.mock import Mock, patch
from django.test import RequestFactory
from tracker.views import NintendoScraperAPIView


@pytest.fixture
def request_factory():
    """Create Django request factory."""
    return RequestFactory()


class TestNintendoScraperAPIView:
    """Tests for the NintendoScraperAPIView."""

    @patch('tracker.views.NintendoAmiiboScraper')
    def test_post_success(self, mock_scraper_class, request_factory):
        """Test successful POST request to scraper endpoint."""
        # Mock scraper result
        mock_scraper = Mock()
        mock_scraper.run.return_value = {
            "status": "success",
            "matched": 10,
            "new": 2,
            "updated": 5,
        }
        mock_scraper_class.return_value = mock_scraper

        # Create POST request
        request = request_factory.post('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Mock log_action to avoid session requirement
        with patch.object(view, 'log_action'):
            # Call view
            response = view.post(request)

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["status"] == "success"
        assert data["matched"] == 10
        assert data["new"] == 2
        assert data["updated"] == 5

        # Verify scraper was called with force=True
        mock_scraper.run.assert_called_once_with(force=True)

    @patch('tracker.views.NintendoAmiiboScraper')
    def test_post_error(self, mock_scraper_class, request_factory):
        """Test POST request with scraper error."""
        # Mock scraper to raise exception
        mock_scraper = Mock()
        mock_scraper.run.side_effect = Exception("Scraper failed")
        mock_scraper_class.return_value = mock_scraper

        # Create POST request
        request = request_factory.post('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Mock log_action to avoid session requirement
        with patch.object(view, 'log_action'):
            # Call view
            response = view.post(request)

        # Verify error response
        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["status"] == "error"
        assert "Scraper failed" in data["message"]

    def test_get_health_check(self, request_factory):
        """Test GET request returns health check info."""
        # Create GET request
        request = request_factory.get('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Call view
        response = view.get(request)

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["status"] == "ready"
        assert "endpoint" in data
        assert "POST" in data["endpoint"]

    @patch('tracker.views.NintendoAmiiboScraper')
    def test_logging_on_success(self, mock_scraper_class, request_factory):
        """Test that successful scraper execution is logged."""
        # Mock scraper result
        mock_scraper = Mock()
        mock_scraper.run.return_value = {
            "status": "success",
            "matched": 5,
            "new": 1,
            "updated": 2,
        }
        mock_scraper_class.return_value = mock_scraper

        # Create POST request
        request = request_factory.post('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Mock logging
        with patch.object(view, 'log_action') as mock_log:
            response = view.post(request)

            # Verify logging was called
            assert mock_log.called
            call_args = mock_log.call_args
            assert "scraper-api" in call_args[0][0]  # Either triggered or error

    @patch('tracker.views.NintendoAmiiboScraper')
    def test_logging_on_error(self, mock_scraper_class, request_factory):
        """Test that scraper errors are logged."""
        # Mock scraper to raise exception
        mock_scraper = Mock()
        mock_scraper.run.side_effect = Exception("Test error")
        mock_scraper_class.return_value = mock_scraper

        # Create POST request
        request = request_factory.post('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Mock logging
        with patch.object(view, 'log_action') as mock_log:
            response = view.post(request)

            # Verify error logging was called
            assert mock_log.called
            call_args = mock_log.call_args
            assert "error" in call_args[0][0].lower()  # error in event name


class TestScraperAPIIntegration:
    """Integration tests for scraper API endpoint."""

    @patch('tracker.scrapers.requests.get')
    @patch('tracker.scrapers.NintendoAmiiboScraper.load_existing_amiibos')
    @patch('tracker.scrapers.NintendoAmiiboScraper.save_amiibos')
    def test_full_api_workflow(self, mock_save, mock_load, mock_get, request_factory):
        """Test complete workflow from API call to scraper execution."""
        # Mock existing amiibos
        mock_load.return_value = [
            {
                "name": "Mario",
                "release": {},
            }
        ]

        # Mock Nintendo website
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <a href="/us/amiibo/detail/mario/" aria-label="Mario">
                <p>Super Mario series</p>
                <p>Available 11/21/2014</p>
            </a>
        </html>
        """
        mock_get.return_value = mock_response

        # Create API request
        request = request_factory.post('/api/scrape-nintendo/')
        view = NintendoScraperAPIView()

        # Mock log_action to avoid session requirement
        with patch.object(view, 'log_action'):
            # Call API
            response = view.post(request)

        # Verify successful response
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["status"] == "success"

        # Verify scraper executed
        assert mock_get.called
        assert mock_save.called
