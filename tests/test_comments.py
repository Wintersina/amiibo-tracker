import pytest
from django.core.cache import cache
from django.http import Http404
from django.test import RequestFactory

from google.api_core.exceptions import ResourceExhausted

from tracker import views


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


AMIIBO_ID = "04380001-03000502"
DETAIL_PATH = f"/blog/number-released/amiibo/{AMIIBO_ID}/"
POST_PATH = f"{DETAIL_PATH}comment/"


def _post(rf, body="Hello world", session=None):
    request = rf.post(POST_PATH, data={"body": body})
    request.session = session if session is not None else {}
    return request


def _logged_in_session():
    return {
        "user_email": "fan@example.com",
        "user_name": "Mario Fan",
    }


# ---------------------------------------------------------------------------
# PostCommentView
# ---------------------------------------------------------------------------


def test_post_redirects_to_login_when_anonymous(rf):
    response = views.PostCommentView.as_view()(_post(rf), amiibo_id=AMIIBO_ID)
    assert response.status_code == 302
    assert response.url.endswith("/oauth-login/")


def test_post_rejects_malformed_amiibo_id(rf):
    with pytest.raises(Http404):
        views.PostCommentView.as_view()(
            _post(rf, session=_logged_in_session()),
            amiibo_id="not-a-real-id",
        )


def test_post_rejects_empty_body(rf, monkeypatch):
    called = []
    monkeypatch.setattr(views, "add_comment", lambda **kw: called.append(kw) or "x")

    response = views.PostCommentView.as_view()(
        _post(rf, body="   ", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=empty")
    assert called == []


def test_post_rejects_overlong_body(rf, monkeypatch):
    called = []
    monkeypatch.setattr(views, "add_comment", lambda **kw: called.append(kw) or "x")

    long_body = "a" * (views.COMMENT_BODY_MAX_LEN + 1)
    response = views.PostCommentView.as_view()(
        _post(rf, body=long_body, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=too_long")
    assert called == []


def test_post_success_calls_wrapper_and_busts_cache(rf, monkeypatch):
    captured = {}

    def fake_add(**kwargs):
        captured.update(kwargs)
        return "new-doc-id"

    monkeypatch.setattr(views, "add_comment", fake_add)

    cache.set(f"comments:{AMIIBO_ID}", ["stale"], 60)

    response = views.PostCommentView.as_view()(
        _post(rf, body="great figure", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=ok")
    assert captured["amiibo_id"] == AMIIBO_ID
    assert captured["user_email"] == "fan@example.com"
    assert captured["display_name"] == "Mario Fan"
    assert captured["body"] == "great figure"
    assert cache.get(f"comments:{AMIIBO_ID}") is None


def test_post_handles_quota_exhausted(rf, monkeypatch):
    def boom(**kwargs):
        raise ResourceExhausted("quota")

    monkeypatch.setattr(views, "add_comment", boom)

    response = views.PostCommentView.as_view()(
        _post(rf, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=server_busy")


def test_post_handles_unexpected_firestore_error(rf, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("network died")

    monkeypatch.setattr(views, "add_comment", boom)

    response = views.PostCommentView.as_view()(
        _post(rf, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=server_busy")


def test_per_user_rate_limit_trips_after_max(rf, monkeypatch):
    monkeypatch.setattr(views, "add_comment", lambda **kw: "id")

    session = _logged_in_session()
    for i in range(views.COMMENT_PER_USER_MAX):
        response = views.PostCommentView.as_view()(
            _post(rf, body=f"comment {i}", session=session),
            amiibo_id=AMIIBO_ID,
        )
        assert response.url.endswith("?comment=ok"), f"iter {i} unexpectedly limited"

    blocked = views.PostCommentView.as_view()(
        _post(rf, body="one too many", session=session),
        amiibo_id=AMIIBO_ID,
    )
    assert blocked.url.endswith("?comment=rate_limited")


# ---------------------------------------------------------------------------
# AmiiboDetailView — comment loading side
# ---------------------------------------------------------------------------


def test_detail_view_passes_comments_to_template(rf, monkeypatch):
    fake_comments = [
        {
            "id": "1",
            "amiibo_id": AMIIBO_ID,
            "display_name": "Luigi",
            "body": "Cool",
            "user_email": "l@example.com",
            "created_at": None,
            "is_hidden": False,
        }
    ]
    monkeypatch.setattr(views, "list_comments", lambda *a, **kw: fake_comments)

    request = rf.get(DETAIL_PATH)
    request.session = {}
    response = views.AmiiboDetailView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"Luigi" in response.content
    assert b"Cool" in response.content


def test_detail_view_renders_banner_from_query_string(rf, monkeypatch):
    monkeypatch.setattr(views, "list_comments", lambda *a, **kw: [])

    request = rf.get(DETAIL_PATH + "?comment=rate_limited")
    request.session = {}
    response = views.AmiiboDetailView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"posting too quickly" in response.content.lower()


def test_detail_view_falls_back_to_empty_when_firestore_fails(rf, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(views, "list_comments", boom)

    request = rf.get(DETAIL_PATH)
    request.session = {}
    response = views.AmiiboDetailView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"No comments yet" in response.content
