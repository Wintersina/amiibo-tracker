import pytest
from django.test import RequestFactory
from django.http import Http404
from unittest.mock import Mock

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
        assert log_calls[0][1]["total_posts"] == 4


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
        not_found_logs = [call for call in log_calls if call[0] == "blog-post-not-found"]
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
        monkeypatch.setattr(
            views.BlogPostView, "_fetch_remote_amiibos", failing_fetch
        )

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
