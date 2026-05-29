"""Shared, pluggable comment flow.

One place owns the whole comment lifecycle so amiibo-detail pages, blog posts,
and any future page behave identically:

* POST: subclass :class:`CommentPostView`, set ``collection`` / ``key_field`` /
  ``log_prefix`` and implement ``resolve_key`` / ``redirect_to`` / ``cache_key``.
  Validation (empty / too long / hate-speech moderation), rate limiting, the
  Firestore write, and cache busting are handled here.
* GET: call :func:`load_comments` and :func:`comment_banner_for`, then render
  the ``tracker/_comments.html`` partial.

Moderation policy lives in :mod:`tracker.moderation`: racist slurs are rejected;
ordinary profanity and rude-but-not-hateful comments are allowed.
"""

from django.core.cache import cache
from django.shortcuts import redirect
from django.views import View
from google.api_core.exceptions import ResourceExhausted

from tracker.firestore_client import (
    add_comment,
    delete_comment,
    get_comment,
    list_comments,
)
from tracker.helpers import LoggingMixin, check_rate_limit
from tracker.moderation import contains_hate_speech

COMMENT_BODY_MAX_LEN = 2000
COMMENT_PER_USER_MAX = 5
COMMENT_PER_USER_WINDOW = 600  # 10 minutes


def comment_banner_for(status):
    """Map a ``?comment=<status>`` query value to a (level, message) banner."""
    return {
        "ok": ("success", "Comment posted."),
        "blocked": (
            "error",
            "Your comment wasn't posted. Please keep it free of racist or hateful language.",
        ),
        "rate_limited": (
            "error",
            "You're posting too quickly. Try again in a few minutes.",
        ),
        "too_long": (
            "error",
            f"Comment too long (max {COMMENT_BODY_MAX_LEN} characters).",
        ),
        "empty": ("error", "Comment can't be empty."),
        "server_busy": (
            "error",
            "Comments are temporarily unavailable. Please try again later.",
        ),
        "deleted": ("success", "Comment deleted."),
        "forbidden": ("error", "You can only delete your own comments."),
        "bad_parent": ("error", "That comment is no longer available to reply to."),
    }.get(status)


def build_comment_threads(comments):
    """Group a flat, newest-first comment list into one-level reply threads.

    Each returned thread is a comment dict with a ``replies`` list (oldest-first,
    the natural reading order for a conversation). Replies whose parent is not in
    the visible set — the parent was hidden by moderation, deleted by its author,
    or fell outside the fetch window — are collected under a ``removed`` tombstone
    so the surviving replies aren't silently dropped.
    """
    replies_by_parent = {}
    top_level = []
    for c in comments:
        parent_id = c.get("parent_id")
        if parent_id:
            replies_by_parent.setdefault(parent_id, []).append(c)
        else:
            top_level.append(c)

    threads = []
    seen = set()
    for c in top_level:
        seen.add(c["id"])
        thread = dict(c)
        thread["removed"] = False
        thread["replies"] = list(reversed(replies_by_parent.get(c["id"], [])))
        threads.append(thread)

    for parent_id, replies in replies_by_parent.items():
        if parent_id in seen:
            continue
        threads.append(
            {
                "id": parent_id,
                "removed": True,
                "replies": list(reversed(replies)),
            }
        )

    return threads


def load_comments(
    collection,
    key_field,
    key_value,
    cache_key,
    *,
    logger=None,
    request=None,
    log_event="comments-load-failed",
    limit=50,
):
    """Return cached comments for a key, loading from Firestore on a miss.

    The flat Firestore list is cached; threads are assembled per request (cheap)
    so reply nesting always reflects the current visible set.

    Failures degrade to an empty list (optionally logged via ``logger``) so a
    Firestore hiccup never takes down the host page.
    """
    comments = cache.get(cache_key)
    if comments is None:
        try:
            comments = list_comments(collection, key_field, key_value, limit=limit)
        except Exception as exc:
            if logger is not None:
                logger.log_action(
                    log_event,
                    request,
                    level="warning",
                    error=str(exc),
                    **{key_field: key_value},
                )
            comments = []
        cache.set(cache_key, comments, 60)
    return build_comment_threads(comments)


class CommentPostView(View, LoggingMixin):
    """Base POST handler for creating a comment.

    Subclasses provide the storage identity and URL/cache wiring:

    * ``collection`` / ``key_field`` — Firestore collection and key field name.
    * ``log_prefix`` — prefix for log_action events (e.g. ``"comment"``).
    * ``resolve_key(request, **kwargs)`` — validate route args, return the key
      value (e.g. amiibo id / slug) or raise ``Http404``.
    * ``redirect_to(key_value, status)`` — where to send the user afterwards.
    * ``cache_key(key_value)`` — the listing cache key to bust on success.
    """

    collection: str = ""
    key_field: str = ""
    log_prefix: str = "comment"

    def resolve_key(self, request, **kwargs):  # pragma: no cover - abstract
        raise NotImplementedError

    def redirect_to(self, key_value, status):  # pragma: no cover - abstract
        raise NotImplementedError

    def cache_key(self, key_value):  # pragma: no cover - abstract
        raise NotImplementedError

    def _key_context(self, key_value):
        return {self.key_field: key_value}

    def _valid_reply_parent(self, key_value, parent_id):
        """A reply target must exist on this page, be visible, and be top-level.

        Rejecting parents that already have a ``parent_id`` keeps threading one
        level deep — a reply to a reply isn't allowed.
        """
        try:
            parent = get_comment(self.collection, parent_id)
        except Exception:
            return False
        return bool(
            parent
            and parent.get(self.key_field) == key_value
            and not parent.get("is_hidden")
            and not parent.get("parent_id")
        )

    def post(self, request, **kwargs):
        key_value = self.resolve_key(request, **kwargs)

        user_email = request.session.get("user_email")
        user_name = request.session.get("user_name") or "Anonymous"
        if not user_email:
            return redirect("oauth_login")

        body = (request.POST.get("body") or "").strip()
        if not body:
            return self.redirect_to(key_value, "empty")
        if len(body) > COMMENT_BODY_MAX_LEN:
            return self.redirect_to(key_value, "too_long")
        if contains_hate_speech(body):
            self.log_action(
                f"{self.log_prefix}-blocked-hate-speech",
                request,
                level="warning",
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "blocked")

        ip_violation = check_rate_limit(
            request,
            bucket="post_comment",
            per_ip_max=10,
            per_ip_window=600,
            global_max=200,
            global_window=600,
        )
        user_key = f"ratelimit:post_comment:user:{user_email}"
        user_count = cache.get(user_key, 0)
        if ip_violation or user_count >= COMMENT_PER_USER_MAX:
            self.log_action(
                f"{self.log_prefix}-rate-limited",
                request,
                level="warning",
                reason=ip_violation or "per-user limit",
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "rate_limited")
        cache.set(user_key, user_count + 1, COMMENT_PER_USER_WINDOW)

        parent_id = (request.POST.get("parent_id") or "").strip() or None
        if parent_id and not self._valid_reply_parent(key_value, parent_id):
            self.log_action(
                f"{self.log_prefix}-bad-parent",
                request,
                level="warning",
                parent_id=parent_id,
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "bad_parent")

        try:
            doc_id = add_comment(
                collection=self.collection,
                key_field=self.key_field,
                key_value=key_value,
                user_email=user_email,
                display_name=user_name,
                body=body,
                parent_id=parent_id,
            )
        except ResourceExhausted:
            self.log_action(
                f"{self.log_prefix}-quota-exhausted",
                request,
                level="error",
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "server_busy")
        except Exception as exc:
            self.log_action(
                f"{self.log_prefix}-write-failed",
                request,
                level="error",
                error=str(exc),
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "server_busy")

        cache.delete(self.cache_key(key_value))
        self.log_action(
            f"{self.log_prefix}-posted",
            request,
            comment_id=doc_id,
            parent_id=parent_id,
            **self._key_context(key_value),
        )
        return self.redirect_to(key_value, "ok")


class CommentDeleteView(View, LoggingMixin):
    """Base POST handler for deleting one's own comment.

    Shares ``collection`` / ``key_field`` / ``resolve_key`` / ``redirect_to`` /
    ``cache_key`` with the matching :class:`CommentPostView` subclass (supplied
    via a page-identity mixin). Authorship is enforced in
    :func:`tracker.firestore_client.delete_comment`; a non-author or missing
    comment yields a ``forbidden`` banner rather than a hard error.
    """

    collection: str = ""
    key_field: str = ""
    log_prefix: str = "comment"

    def resolve_key(self, request, **kwargs):  # pragma: no cover - abstract
        raise NotImplementedError

    def redirect_to(self, key_value, status):  # pragma: no cover - abstract
        raise NotImplementedError

    def cache_key(self, key_value):  # pragma: no cover - abstract
        raise NotImplementedError

    def _key_context(self, key_value):
        return {self.key_field: key_value}

    def post(self, request, comment_id=None, **kwargs):
        key_value = self.resolve_key(request, **kwargs)

        user_email = request.session.get("user_email")
        if not user_email:
            return redirect("oauth_login")

        try:
            deleted = delete_comment(self.collection, comment_id, user_email)
        except ResourceExhausted:
            self.log_action(
                f"{self.log_prefix}-quota-exhausted",
                request,
                level="error",
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "server_busy")
        except Exception as exc:
            self.log_action(
                f"{self.log_prefix}-delete-failed",
                request,
                level="error",
                error=str(exc),
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "server_busy")

        if not deleted:
            self.log_action(
                f"{self.log_prefix}-delete-denied",
                request,
                level="warning",
                comment_id=comment_id,
                **self._key_context(key_value),
            )
            return self.redirect_to(key_value, "forbidden")

        cache.delete(self.cache_key(key_value))
        self.log_action(
            f"{self.log_prefix}-deleted",
            request,
            comment_id=comment_id,
            **self._key_context(key_value),
        )
        return self.redirect_to(key_value, "deleted")
