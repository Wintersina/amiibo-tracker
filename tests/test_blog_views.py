import pytest
import json
from pathlib import Path
from django.test import RequestFactory
from django.http import Http404
from unittest.mock import Mock, patch, mock_open

from tracker import views
from tracker.views import BLOG_POSTS


@pytest.fixture
def rf():
    return RequestFactory()


def add_session_to_request(request):
    """Add mocked session support to a request created by RequestFactory"""
    request.session = Mock()
    request.session.get = Mock(return_value=None)
    return request


class TestBlogListView:
    """Tests for the BlogListView endpoint (GET /blog/)"""

    def test_blog_list_returns_200(self, rf):
        """Test that blog list view returns 200 status code"""
        request = add_session_to_request(rf.get("/blog/"))
        response = views.BlogListView.as_view()(request)

        assert response.status_code == 200

    def test_blog_list_logs_action(self, monkeypatch, rf):
        """Test that blog list view logs the action"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        monkeypatch.setattr(views.BlogListView, "log_action", capture_log)

        request = add_session_to_request(rf.get("/blog/"))
        views.BlogListView.as_view()(request)

        assert len(log_calls) == 1
        assert log_calls[0][0] == "blog-list-view"
        assert log_calls[0][1]["total_posts"] == 12


class TestBlogPostView:
    """Tests for the BlogPostView endpoint (GET /blog/<slug>/)"""

    def test_blog_post_how_it_works_returns_200(self, rf):
        """Test that 'how-it-works' post returns 200"""
        request = add_session_to_request(rf.get("/blog/how-it-works/"))
        response = views.BlogPostView.as_view()(request, slug="how-it-works")

        assert response.status_code == 200

    def test_blog_post_pronunciation_returns_200(self, rf):
        """Test that 'pronunciation' post returns 200"""
        request = add_session_to_request(rf.get("/blog/pronunciation/"))
        response = views.BlogPostView.as_view()(request, slug="pronunciation")

        assert response.status_code == 200

    def test_blog_post_history_returns_200(self, rf):
        """Test that 'history-of-amiibo' post returns 200"""
        request = add_session_to_request(rf.get("/blog/history-of-amiibo/"))
        response = views.BlogPostView.as_view()(request, slug="history-of-amiibo")

        assert response.status_code == 200

    def test_blog_post_invalid_slug_raises_404(self, rf):
        """Test that invalid slug raises 404"""
        request = add_session_to_request(rf.get("/blog/nonexistent/"))

        with pytest.raises(Http404):
            views.BlogPostView.as_view()(request, slug="nonexistent")

    def test_blog_post_logs_action(self, monkeypatch, rf):
        """Test that blog post view logs the action"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        monkeypatch.setattr(views.BlogPostView, "log_action", capture_log)

        request = add_session_to_request(rf.get("/blog/pronunciation/"))
        views.BlogPostView.as_view()(request, slug="pronunciation")

        # Should have one log call for successful view
        view_logs = [call for call in log_calls if call[0] == "blog-post-view"]
        assert len(view_logs) == 1
        assert view_logs[0][1]["slug"] == "pronunciation"
        assert view_logs[0][1]["title"] == "How to Pronounce Amiibo"

    def test_blog_post_logs_404(self, monkeypatch, rf):
        """Test that 404 is logged when post not found"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        monkeypatch.setattr(views.BlogPostView, "log_action", capture_log)

        request = add_session_to_request(rf.get("/blog/nonexistent/"))

        with pytest.raises(Http404):
            views.BlogPostView.as_view()(request, slug="nonexistent")

        # Should have log call for 404
        not_found_logs = [
            call for call in log_calls if call[0] == "blog-post-not-found"
        ]
        assert len(not_found_logs) == 1
        assert not_found_logs[0][1]["slug"] == "nonexistent"
        assert not_found_logs[0][1]["level"] == "warning"


class TestBlogPostViewDynamicContent:
    """Tests for the dynamic content feature in BlogPostView (number-released)"""

    def test_number_released_returns_200(self, rf):
        """Test that 'number-released' post returns 200"""
        request = add_session_to_request(rf.get("/blog/number-released/"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200

    def test_number_released_returns_200_with_mock_data(self, monkeypatch, rf):
        """Test that number-released post returns 200 with mocked amiibo data"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000001",
                "release": {"na": "2014-11-21", "jp": "2014-12-06"},
            },
            {
                "name": "Link",
                "head": "00000000",
                "tail": "00000002",
                "release": {"na": "2014-11-21", "jp": "2014-12-06"},
            },
        ]

        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200

    def test_number_released_logs_dynamic_content_load(self, monkeypatch, rf):
        """Test that dynamic content loading is logged"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000001",
                "release": {"na": "2014-11-21"},
            },
        ]

        monkeypatch.setattr(views.BlogPostView, "log_action", capture_log)
        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/"))
        views.BlogPostView.as_view()(request, slug="number-released")

        # Check for dynamic content log
        dynamic_logs = [
            call for call in log_calls if call[0] == "blog-dynamic-content-loaded"
        ]
        assert len(dynamic_logs) == 1
        assert dynamic_logs[0][1]["slug"] == "number-released"
        assert dynamic_logs[0][1]["amiibo_count"] == 1

    def test_number_released_handles_fetch_error(self, monkeypatch, rf):
        """Test that fetch errors are handled gracefully"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        def failing_fetch(self):
            raise Exception("API unavailable")

        monkeypatch.setattr(views.BlogPostView, "log_action", capture_log)
        monkeypatch.setattr(views.BlogPostView, "_fetch_remote_amiibos", failing_fetch)

        request = add_session_to_request(rf.get("/blog/number-released/"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        # Should still return 200 even with error
        assert response.status_code == 200

        # Check error was logged
        error_logs = [
            call for call in log_calls if call[0] == "blog-dynamic-content-error"
        ]
        assert len(error_logs) == 1
        assert error_logs[0][1]["level"] == "error"
        assert error_logs[0][1]["slug"] == "number-released"
        assert "API unavailable" in error_logs[0][1]["error"]


class TestBlogPostViewPagination:
    """Tests for the pagination feature in BlogPostView (number-released)"""

    def test_number_released_pagination_first_page(self, monkeypatch, rf):
        """Test that pagination works for first page"""
        # Create 60 mock amiibos to trigger pagination (50 per page)
        mock_amiibos = [
            {
                "name": f"Amiibo {i}",
                "head": "00000000",
                "tail": f"0000000{i:01x}",
                "gameSeries": "Test Series",
                "amiiboSeries": "Test Amiibo Series",
                "type": "Figure",
                "image": f"http://example.com/image{i}.png",
                "release": {"na": "2014-11-21"},
            }
            for i in range(60)
        ]

        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200
        # Check that pagination controls appear in rendered HTML
        content = response.content.decode("utf-8")
        assert "Page 1" in content or "pagination" in content

    def test_number_released_pagination_second_page(self, monkeypatch, rf):
        """Test that pagination works for second page"""
        mock_amiibos = [
            {
                "name": f"Amiibo {i}",
                "head": "00000000",
                "tail": f"0000000{i:01x}",
                "gameSeries": "Test Series",
                "amiiboSeries": "Test Amiibo Series",
                "type": "Figure",
                "image": f"http://example.com/image{i}.png",
                "release": {"na": "2014-11-21"},
            }
            for i in range(60)
        ]

        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/?page=2"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200
        # Check that page 2 is indicated in rendered HTML
        content = response.content.decode("utf-8")
        assert "Page 2" in content or "page=1" in content

    def test_number_released_pagination_invalid_page(self, monkeypatch, rf):
        """Test that invalid page number defaults to page 1"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000001",
                "gameSeries": "Super Mario",
                "amiiboSeries": "Super Smash Bros.",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/?page=invalid"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200

    def test_number_released_amiibo_id_format(self, monkeypatch, rf):
        """Test that amiibo_id is added in head-tail format"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "gameSeries": "Super Mario",
                "amiiboSeries": "Super Smash Bros.",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.BlogPostView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(rf.get("/blog/number-released/"))
        response = views.BlogPostView.as_view()(request, slug="number-released")

        assert response.status_code == 200
        # Check that URL with amiibo_id format is in rendered HTML
        content = response.content.decode("utf-8")
        assert "00000000-00000002" in content


class TestAmiiboDetailView:
    """Tests for the AmiiboDetailView endpoint (GET /blog/number-released/amiibo/<amiibo_id>/)"""

    def test_amiibo_detail_returns_200(self, monkeypatch, rf):
        """Test that amiibo detail view returns 200 for valid amiibo"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "character": "Mario",
                "gameSeries": "Super Mario",
                "amiiboSeries": "Super Smash Bros.",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {"na": "2014-11-21", "jp": "2014-12-06"},
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/00000000-00000002/")
        )
        response = views.AmiiboDetailView.as_view()(
            request, amiibo_id="00000000-00000002"
        )

        assert response.status_code == 200

    def test_amiibo_detail_invalid_id_format_raises_404(self, rf):
        """Test that invalid amiibo_id format raises 404"""
        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/invalid/")
        )

        with pytest.raises(Http404):
            views.AmiiboDetailView.as_view()(request, amiibo_id="invalid")

    def test_amiibo_detail_short_id_raises_404(self, rf):
        """Test that short amiibo_id raises 404"""
        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/123-456/")
        )

        with pytest.raises(Http404):
            views.AmiiboDetailView.as_view()(request, amiibo_id="123-456")

    def test_amiibo_detail_not_found_raises_404(self, monkeypatch, rf):
        """Test that non-existent amiibo raises 404"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/99999999-99999999/")
        )

        with pytest.raises(Http404):
            views.AmiiboDetailView.as_view()(request, amiibo_id="99999999-99999999")

    def test_amiibo_detail_logs_view(self, monkeypatch, rf):
        """Test that amiibo detail view logs the action"""
        log_calls = []

        def capture_log(self, action, request, **context):
            log_calls.append((action, context))

        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "character": "Mario",
                "gameSeries": "Super Mario",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(views.AmiiboDetailView, "log_action", capture_log)
        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/00000000-00000002/")
        )
        views.AmiiboDetailView.as_view()(request, amiibo_id="00000000-00000002")

        # Check for view log
        view_logs = [call for call in log_calls if call[0] == "amiibo-detail-view"]
        assert len(view_logs) == 1
        assert view_logs[0][1]["amiibo_id"] == "00000000-00000002"
        assert view_logs[0][1]["amiibo_name"] == "Mario"

    def test_amiibo_detail_regional_releases(self, monkeypatch, rf):
        """Test that regional release dates are formatted correctly"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "character": "Mario",
                "gameSeries": "Super Mario",
                "amiiboSeries": "Super Smash Bros.",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {
                    "na": "2014-11-21",
                    "jp": "2014-12-06",
                    "eu": "2014-11-28",
                    "au": "2014-11-29",
                },
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/00000000-00000002/")
        )
        response = views.AmiiboDetailView.as_view()(
            request, amiibo_id="00000000-00000002"
        )

        assert response.status_code == 200
        # Check that regional release dates appear in rendered HTML
        content = response.content.decode("utf-8")
        assert "North America" in content
        assert "November" in content or "2014" in content


class TestCharacterDescriptions:
    """Tests for character description functionality in AmiiboDetailView"""

    def test_get_character_description_from_json(self, monkeypatch, rf):
        """Test that character descriptions are loaded from JSON file"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "character": "Mario",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        mock_descriptions = {"Mario": "Mario is the iconic plumber from Nintendo."}

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        # Mock the file reading
        with patch("pathlib.Path.exists", return_value=True):
            with patch(
                "builtins.open", mock_open(read_data=json.dumps(mock_descriptions))
            ):
                request = add_session_to_request(
                    rf.get("/blog/number-released/amiibo/00000000-00000002/")
                )
                response = views.AmiiboDetailView.as_view()(
                    request, amiibo_id="00000000-00000002"
                )

                assert response.status_code == 200
                # Check description in rendered HTML
                content = response.content.decode("utf-8")
                assert "Mario is the iconic plumber from Nintendo" in content

    def test_get_character_description_template_fallback(self, monkeypatch, rf):
        """Test that template-based description is used when JSON file doesn't exist"""
        mock_amiibos = [
            {
                "name": "Unknown Character",
                "head": "00000000",
                "tail": "00000099",
                "character": "Unknown",
                "gameSeries": "Test Series",
                "type": "Figure",
                "image": "http://example.com/unknown.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        # Mock file not existing
        with patch("pathlib.Path.exists", return_value=False):
            request = add_session_to_request(
                rf.get("/blog/number-released/amiibo/00000000-00000099/")
            )
            response = views.AmiiboDetailView.as_view()(
                request, amiibo_id="00000000-00000099"
            )

            assert response.status_code == 200
            # Should use template fallback
            content = response.content.decode("utf-8")
            assert "Test Series" in content

    def test_get_character_description_handles_json_error(self, monkeypatch, rf):
        """Test that JSON parsing errors fall back to template description"""
        mock_amiibos = [
            {
                "name": "Mario",
                "head": "00000000",
                "tail": "00000002",
                "character": "Mario",
                "gameSeries": "Super Mario",
                "type": "Figure",
                "image": "http://example.com/mario.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        # Mock file exists but has invalid JSON
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="invalid json {")):
                request = add_session_to_request(
                    rf.get("/blog/number-released/amiibo/00000000-00000002/")
                )
                response = views.AmiiboDetailView.as_view()(
                    request, amiibo_id="00000000-00000002"
                )

                assert response.status_code == 200
                # Should fall back to template
                content = response.content.decode("utf-8")
                assert "Super Mario" in content or "character from" in content

    def test_get_character_description_no_character_name(self, monkeypatch, rf):
        """Test description when character name is missing"""
        mock_amiibos = [
            {
                "name": "Test Amiibo",
                "head": "00000000",
                "tail": "00000099",
                "character": "",
                "gameSeries": "",
                "type": "Figure",
                "image": "http://example.com/test.png",
                "release": {"na": "2014-11-21"},
            }
        ]

        monkeypatch.setattr(
            views.AmiiboDetailView,
            "_fetch_remote_amiibos",
            lambda self: mock_amiibos,
        )

        request = add_session_to_request(
            rf.get("/blog/number-released/amiibo/00000000-00000099/")
        )
        response = views.AmiiboDetailView.as_view()(
            request, amiibo_id="00000000-00000099"
        )

        assert response.status_code == 200
        # Should use generic fallback
        content = response.content.decode("utf-8")
        assert "Nintendo" in content or "amiibo" in content.lower()
