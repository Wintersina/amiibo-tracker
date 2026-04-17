"""Grafana Cloud Loki integration.

Ships structured logs from the Django app to Grafana Cloud. Emails are hashed
with a server-side salt before they leave the process — Loki only ever sees an
opaque `user_hash`, never the raw address.

Configuration is driven by environment variables so local development stays a
no-op unless explicitly opted in:

    LOKI_URL        e.g. https://logs-prod-042.grafana.net
    LOKI_USER       numeric Grafana stack user id
    LOKI_API_KEY    Grafana Cloud API token
    LOKI_HASH_SALT  per-deployment salt for email hashing
    ENV_NAME        tags emitted logs (development/production)
"""

import hashlib
import logging
import os


logger = logging.getLogger(__name__)

_LOKI_PATH = "/loki/api/v1/push"


def hash_email(email):
    if not email:
        return None
    salt = os.environ.get("LOKI_HASH_SALT", "")
    digest = hashlib.sha256(f"{salt}{email.strip().lower()}".encode("utf-8")).hexdigest()
    return digest[:16]


class LokiHandler(logging.Handler):
    """Dispatches to python-logging-loki when fully configured; otherwise no-op.

    Implemented as a passthrough so the Django LOGGING dict can always reference
    it by dotted path without blowing up when the env isn't wired yet.
    """

    def __init__(self, level=logging.INFO):
        super().__init__(level=level)
        self._inner = self._build_inner()

    @staticmethod
    def _build_inner():
        url = os.environ.get("LOKI_URL")
        user = os.environ.get("LOKI_USER")
        token = os.environ.get("LOKI_API_KEY")
        env_name = os.environ.get("ENV_NAME", "development")

        if not (url and user and token):
            return None

        try:
            import logging_loki
        except ImportError:
            logger.warning("loki-handler-missing-dependency | install python-logging-loki")
            return None

        handler = logging_loki.LokiHandler(
            url=f"{url.rstrip('/')}{_LOKI_PATH}",
            tags={"app": "amiibo-tracker", "env": env_name},
            auth=(user, token),
            version="1",
        )
        return handler

    def emit(self, record):
        if self._inner is None:
            return
        try:
            self._inner.emit(record)
        except Exception:
            self.handleError(record)


class PageViewMiddleware:
    """Emit a `page-view` log entry for human-facing GET requests.

    Anonymous visits are tagged with authenticated=false and a null user_hash so
    the login funnel (visit -> login -> action) is visible in Grafana without
    ever surfacing raw emails.
    """

    SKIP_PREFIXES = (
        "/static/",
        "/staticfiles/",
        "/robots.txt",
        "/sitemap",
        "/api/remove-bg/",
        "/api/scrape-nintendo/",
        "/toggle/",
        "/toggle-dark-mode/",
        "/toggle-type-filter/",
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self._logger = logging.getLogger("tracker.pageview")

    def __call__(self, request):
        response = self.get_response(request)
        self._maybe_log(request, response)
        return response

    def _maybe_log(self, request, response):
        if request.method != "GET":
            return
        path = request.path
        if any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return
        try:
            session = getattr(request, "session", None)
            email = session.get("user_email") if session is not None else None
            self._logger.info(
                "page-view[%s]",
                path,
                extra={
                    "event": "page-view",
                    "path": path,
                    "status_code": response.status_code,
                    "user_hash": hash_email(email),
                    "authenticated": bool(email),
                    "referrer": request.META.get("HTTP_REFERER", ""),
                    "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
                },
            )
        except Exception:
            # Observability must never break request handling.
            logger.debug("page-view-log-failed", exc_info=True)
