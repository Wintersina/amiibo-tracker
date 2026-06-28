import pytest
from django.core.cache import cache
from django.http import Http404
from django.test import RequestFactory

from google.api_core.exceptions import ResourceExhausted

from tracker import comments, views


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
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")

    response = views.PostCommentView.as_view()(
        _post(rf, body="   ", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=empty")
    assert called == []


def test_post_rejects_overlong_body(rf, monkeypatch):
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")

    long_body = "a" * (views.COMMENT_BODY_MAX_LEN + 1)
    response = views.PostCommentView.as_view()(
        _post(rf, body=long_body, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=too_long")
    assert called == []


def test_post_rejects_hate_speech(rf, monkeypatch):
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")
    # Simulate the moderation filter flagging the body as hate speech.
    monkeypatch.setattr(comments, "contains_hate_speech", lambda text: True)

    response = views.PostCommentView.as_view()(
        _post(rf, body="some slur here", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=blocked")
    assert called == []  # nothing written when blocked


def test_post_allows_ordinary_profanity(rf, monkeypatch):
    # Real moderation filter (not patched): cussing must pass through.
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")

    response = views.PostCommentView.as_view()(
        _post(
            rf,
            body="this damn figure is so freaking expensive",
            session=_logged_in_session(),
        ),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=ok")
    assert len(called) == 1


def test_post_success_calls_wrapper_and_busts_cache(rf, monkeypatch):
    captured = {}

    def fake_add(**kwargs):
        captured.update(kwargs)
        return "new-doc-id"

    monkeypatch.setattr(comments, "add_comment", fake_add)

    cache.set(f"comments:amiibo:{AMIIBO_ID}", ["stale"], 60)

    response = views.PostCommentView.as_view()(
        _post(rf, body="great figure", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=ok")
    assert captured["collection"] == "amiibo_comments"
    assert captured["key_field"] == "amiibo_id"
    assert captured["key_value"] == AMIIBO_ID
    assert captured["user_email"] == "fan@example.com"
    assert captured["display_name"] == "Mario Fan"
    assert captured["body"] == "great figure"
    assert cache.get(f"comments:amiibo:{AMIIBO_ID}") is None


def test_post_handles_quota_exhausted(rf, monkeypatch):
    def boom(**kwargs):
        raise ResourceExhausted("quota")

    monkeypatch.setattr(comments, "add_comment", boom)

    response = views.PostCommentView.as_view()(
        _post(rf, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=server_busy")


def test_post_handles_unexpected_firestore_error(rf, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("network died")

    monkeypatch.setattr(comments, "add_comment", boom)

    response = views.PostCommentView.as_view()(
        _post(rf, session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.status_code == 302
    assert response.url.endswith("?comment=server_busy")


def test_per_user_rate_limit_trips_after_max(rf, monkeypatch):
    monkeypatch.setattr(comments, "add_comment", lambda **kw: "id")

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
# Replies (parent_id) — PostCommentView
# ---------------------------------------------------------------------------


def _reply(rf, parent_id, body="A reply", session=None):
    request = rf.post(POST_PATH, data={"body": body, "parent_id": parent_id})
    request.session = session if session is not None else {}
    return request


def test_reply_to_valid_parent_passes_parent_id(rf, monkeypatch):
    captured = {}
    monkeypatch.setattr(comments, "add_comment", lambda **kw: captured.update(kw) or "id")
    # A visible, top-level parent on the same amiibo.
    monkeypatch.setattr(
        comments,
        "get_comment",
        lambda collection, doc_id: {
            "id": doc_id,
            "amiibo_id": AMIIBO_ID,
            "is_hidden": False,
            "parent_id": None,
        },
    )

    response = views.PostCommentView.as_view()(
        _reply(rf, "parent-1", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.url.endswith("?comment=ok")
    assert captured["parent_id"] == "parent-1"


def test_reply_to_missing_parent_is_rejected(rf, monkeypatch):
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")
    monkeypatch.setattr(comments, "get_comment", lambda collection, doc_id: None)

    response = views.PostCommentView.as_view()(
        _reply(rf, "ghost", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.url.endswith("?comment=bad_parent")
    assert called == []


def test_reply_to_parent_on_other_page_is_rejected(rf, monkeypatch):
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")
    monkeypatch.setattr(
        comments,
        "get_comment",
        lambda collection, doc_id: {
            "id": doc_id,
            "amiibo_id": "00000000-00000000",  # different amiibo
            "is_hidden": False,
            "parent_id": None,
        },
    )

    response = views.PostCommentView.as_view()(
        _reply(rf, "parent-1", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.url.endswith("?comment=bad_parent")
    assert called == []


def test_reply_to_a_reply_is_rejected(rf, monkeypatch):
    called = []
    monkeypatch.setattr(comments, "add_comment", lambda **kw: called.append(kw) or "x")
    # Parent is itself a reply (has parent_id) → one-level threading guard.
    monkeypatch.setattr(
        comments,
        "get_comment",
        lambda collection, doc_id: {
            "id": doc_id,
            "amiibo_id": AMIIBO_ID,
            "is_hidden": False,
            "parent_id": "grandparent",
        },
    )

    response = views.PostCommentView.as_view()(
        _reply(rf, "a-reply", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
    )

    assert response.url.endswith("?comment=bad_parent")
    assert called == []


# ---------------------------------------------------------------------------
# build_comment_threads
# ---------------------------------------------------------------------------


def test_build_threads_nests_replies_oldest_first():
    # list_comments returns newest-first; replies should read oldest-first.
    flat = [
        {"id": "top", "body": "parent", "parent_id": None},
        {"id": "r2", "body": "second reply", "parent_id": "top"},
        {"id": "r1", "body": "first reply", "parent_id": "top"},
    ]
    threads = comments.build_comment_threads(flat)

    assert len(threads) == 1
    assert threads[0]["id"] == "top"
    assert threads[0]["removed"] is False
    assert [r["id"] for r in threads[0]["replies"]] == ["r1", "r2"]


def test_build_threads_tombstones_orphaned_replies():
    # Parent is absent (hidden/deleted) but its reply survives.
    flat = [{"id": "r1", "body": "orphan reply", "parent_id": "gone"}]
    threads = comments.build_comment_threads(flat)

    assert len(threads) == 1
    assert threads[0]["removed"] is True
    assert threads[0]["id"] == "gone"
    assert [r["id"] for r in threads[0]["replies"]] == ["r1"]


# ---------------------------------------------------------------------------
# DeleteCommentView
# ---------------------------------------------------------------------------


def _delete(rf, comment_id, session=None):
    path = f"{POST_PATH}{comment_id}/delete/"
    request = rf.post(path)
    request.session = session if session is not None else {}
    return request


def test_delete_redirects_to_login_when_anonymous(rf):
    response = views.DeleteCommentView.as_view()(
        _delete(rf, "c1"), amiibo_id=AMIIBO_ID, comment_id="c1"
    )
    assert response.status_code == 302
    assert response.url.endswith("/oauth-login/")


def test_delete_success_busts_cache(rf, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        comments,
        "delete_comment",
        lambda collection, doc_id, user_email: captured.update(
            collection=collection, doc_id=doc_id, user_email=user_email
        )
        or True,
    )
    cache.set(f"comments:amiibo:{AMIIBO_ID}", ["stale"], 60)

    response = views.DeleteCommentView.as_view()(
        _delete(rf, "c1", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
        comment_id="c1",
    )

    assert response.url.endswith("?comment=deleted")
    assert captured == {
        "collection": "amiibo_comments",
        "doc_id": "c1",
        "user_email": "fan@example.com",
    }
    assert cache.get(f"comments:amiibo:{AMIIBO_ID}") is None


def test_delete_denied_when_not_owner(rf, monkeypatch):
    monkeypatch.setattr(
        comments, "delete_comment", lambda collection, doc_id, user_email: False
    )

    response = views.DeleteCommentView.as_view()(
        _delete(rf, "c1", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
        comment_id="c1",
    )

    assert response.url.endswith("?comment=forbidden")


def test_delete_handles_firestore_error(rf, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(comments, "delete_comment", boom)

    response = views.DeleteCommentView.as_view()(
        _delete(rf, "c1", session=_logged_in_session()),
        amiibo_id=AMIIBO_ID,
        comment_id="c1",
    )

    assert response.url.endswith("?comment=server_busy")


# ---------------------------------------------------------------------------
# AmiiboCommentsView — async comments fragment
#
# Comments load via a separate fragment endpoint so the Firestore round-trip
# never blocks the detail page render. The detail page itself no longer embeds
# comments; it ships an empty #comments-root container that fetches this view.
# ---------------------------------------------------------------------------

COMMENTS_PATH = f"{DETAIL_PATH}comments/"


def test_detail_view_does_not_block_on_comments(rf, monkeypatch):
    """The detail page renders without loading comments inline."""

    def boom(*a, **kw):
        raise AssertionError("detail view must not load comments synchronously")

    monkeypatch.setattr(comments, "list_comments", boom)

    request = rf.get(DETAIL_PATH)
    request.session = {}
    response = views.AmiiboDetailView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b'id="comments-root"' in response.content


def test_comments_fragment_renders_comments(rf, monkeypatch):
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
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: fake_comments)

    request = rf.get(COMMENTS_PATH)
    request.session = {}
    response = views.AmiiboCommentsView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"Luigi" in response.content
    assert b"Cool" in response.content


def test_comments_fragment_renders_banner_from_query_string(rf, monkeypatch):
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: [])

    request = rf.get(COMMENTS_PATH + "?comment=rate_limited")
    request.session = {}
    response = views.AmiiboCommentsView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"posting too quickly" in response.content.lower()


def test_comments_fragment_falls_back_to_empty_when_firestore_fails(rf, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(comments, "list_comments", boom)

    request = rf.get(COMMENTS_PATH)
    request.session = {}
    response = views.AmiiboCommentsView.as_view()(request, amiibo_id=AMIIBO_ID)

    assert response.status_code == 200
    assert b"No comments yet" in response.content


# ---------------------------------------------------------------------------
# PostBlogCommentView
# ---------------------------------------------------------------------------


BLOG_SLUG = "resident-evil-amiibo-complete-guide"
BLOG_PATH = f"/blog/{BLOG_SLUG}/"
BLOG_POST_PATH = f"{BLOG_PATH}comment/"


def _blog_post(rf, body="Loved this", session=None):
    request = rf.post(BLOG_POST_PATH, data={"body": body})
    request.session = session if session is not None else {}
    return request


def test_blog_post_404_for_unknown_slug(rf):
    with pytest.raises(Http404):
        views.PostBlogCommentView.as_view()(
            _blog_post(rf, session=_logged_in_session()),
            slug="this-slug-does-not-exist",
        )


def test_blog_post_redirects_to_login_when_anonymous(rf):
    response = views.PostBlogCommentView.as_view()(_blog_post(rf), slug=BLOG_SLUG)
    assert response.status_code == 302
    assert response.url.endswith("/oauth-login/")


def test_blog_post_success_writes_with_slug_key_and_busts_cache(rf, monkeypatch):
    captured = {}

    def fake_add(**kwargs):
        captured.update(kwargs)
        return "blog-doc-id"

    monkeypatch.setattr(comments, "add_comment", fake_add)

    cache.set(f"comments:blog:{BLOG_SLUG}", ["stale"], 60)

    response = views.PostBlogCommentView.as_view()(
        _blog_post(rf, body="nice writeup", session=_logged_in_session()),
        slug=BLOG_SLUG,
    )

    assert response.status_code == 302
    assert response.url.endswith(f"/blog/{BLOG_SLUG}/?comment=ok")
    assert captured["collection"] == "blog_comments"
    assert captured["key_field"] == "slug"
    assert captured["key_value"] == BLOG_SLUG
    assert captured["body"] == "nice writeup"
    assert cache.get(f"comments:blog:{BLOG_SLUG}") is None


def test_blog_post_handles_quota_exhausted(rf, monkeypatch):
    def boom(**kwargs):
        raise ResourceExhausted("quota")

    monkeypatch.setattr(comments, "add_comment", boom)

    response = views.PostBlogCommentView.as_view()(
        _blog_post(rf, session=_logged_in_session()),
        slug=BLOG_SLUG,
    )

    assert response.status_code == 302
    assert response.url.endswith(f"/blog/{BLOG_SLUG}/?comment=server_busy")


# ---------------------------------------------------------------------------
# BlogPostView — comment loading + banner
# ---------------------------------------------------------------------------


def test_blog_view_renders_comments(rf, monkeypatch):
    fake_comments = [
        {
            "id": "1",
            "slug": BLOG_SLUG,
            "display_name": "Peach",
            "body": "Great post",
            "user_email": "p@example.com",
            "created_at": None,
            "is_hidden": False,
        }
    ]
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: fake_comments)

    request = rf.get(BLOG_PATH)
    request.session = {}
    response = views.BlogPostView.as_view()(request, slug=BLOG_SLUG)

    assert response.status_code == 200
    assert b"Peach" in response.content
    assert b"Great post" in response.content


def test_blog_view_renders_banner(rf, monkeypatch):
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: [])

    request = rf.get(BLOG_PATH + "?comment=ok")
    request.session = {}
    response = views.BlogPostView.as_view()(request, slug=BLOG_SLUG)

    assert response.status_code == 200
    assert b"Comment posted." in response.content


# ---------------------------------------------------------------------------
# Header login/logout swap
# ---------------------------------------------------------------------------


def test_header_shows_login_when_anonymous(rf, monkeypatch):
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: [])

    request = rf.get(BLOG_PATH)
    request.session = {}
    response = views.BlogPostView.as_view()(request, slug=BLOG_SLUG)

    assert b"login-start" in response.content
    assert b"logout-start" not in response.content


def test_header_shows_logout_when_logged_in(rf, monkeypatch):
    monkeypatch.setattr(comments, "list_comments", lambda *a, **kw: [])

    request = rf.get(BLOG_PATH)
    request.session = _logged_in_session()
    response = views.BlogPostView.as_view()(request, slug=BLOG_SLUG)

    assert b"logout-start" in response.content
    assert b"login-start" not in response.content
