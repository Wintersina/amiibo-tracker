import json
import logging
import os
import warnings
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

import googleapiclient.discovery
import requests
from gspread.exceptions import APIError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.helpers import (
    LoggingMixin,
    AmiiboRemoteFetchMixin,
    AmiiboLocalFetchMixin,
    check_rate_limit,
)
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager
from tracker.scrapers import AmiiboLifeScraper
from tracker.firestore_client import (
    AMIIBO_COMMENTS_COLLECTION,
    BLOG_COMMENTS_COLLECTION,
)
from tracker.comments import (
    CommentPostView,
    CommentDeleteView,
    load_comments,
    comment_banner_for,
    COMMENT_BODY_MAX_LEN,
    COMMENT_PER_USER_MAX,
    COMMENT_PER_USER_WINDOW,
)
from tracker.authors import DEFAULT_AUTHOR_SLUG, get_author, load_authors
from tracker.seo_helpers import (
    SEOContext,
    generate_meta_description,
    generate_article_schema,
    generate_blog_posting_schema,
    generate_breadcrumb_schema,
    generate_organization_schema,
    generate_website_schema,
)
from tracker.exceptions import (
    GoogleSheetsError,
    SpreadsheetNotFoundError,
    SpreadsheetPermissionError,
    ServiceUnavailableError,
    RateLimitError,
    QuotaExceededError,
    InvalidCredentialsError,
    NetworkError,
    InsufficientScopesError,
)

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


UNSUPPORTED_PUBLIC_AMIIBO_SERIES = {"Pragmata"}
LOCAL_OAUTH_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def filter_public_amiibos(amiibos):
    """Remove unsourced placeholder entries from public catalog views."""
    return [
        amiibo
        for amiibo in amiibos
        if amiibo.get("amiiboSeries") not in UNSUPPORTED_PUBLIC_AMIIBO_SERIES
        and amiibo.get("gameSeries") not in UNSUPPORTED_PUBLIC_AMIIBO_SERIES
    ]


def load_blog_posts():
    """Load blog posts from JSON file."""
    blog_posts_path = Path(__file__).parent / "data" / "blog_posts.json"
    try:
        with blog_posts_path.open(encoding="utf-8") as f:
            data = json.load(f)
            posts = data.get("posts", [])
            for post in posts:
                post.setdefault("author", DEFAULT_AUTHOR_SLUG)
            return posts
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(
            "load-blog-posts-failed | context=%s", json.dumps({"error": str(e)})
        )
        return []


BLOG_POSTS = load_blog_posts()


def is_rate_limit_error(error: Exception) -> bool:
    return isinstance(error, APIError) and getattr(error, "code", None) == 429


def retry_after_seconds(error: APIError, default: int = 30) -> int:
    try:
        return int(error.response.headers.get("Retry-After", default))
    except Exception:
        return default


def rate_limit_json_response(error: APIError):
    wait_seconds = retry_after_seconds(error)
    return JsonResponse(
        {
            "status": "rate_limited",
            "message": "Google Sheets rate limit reached. Please wait before trying again.",
            "retry_after": wait_seconds,
        },
        status=429,
    )


def build_sheet_client_manager(request, creds_json=None) -> GoogleSheetClientManager:
    return GoogleSheetClientManager(
        creds_json=(
            creds_json if creds_json is not None else request.session.get("credentials")
        ),
        spreadsheet_id=request.session.get("spreadsheet_id"),
    )


def ensure_spreadsheet_session(request, manager: GoogleSheetClientManager):
    if not hasattr(manager, "spreadsheet"):
        return None

    spreadsheet = manager.spreadsheet
    if getattr(manager, "spreadsheet_id", None):
        request.session["spreadsheet_id"] = manager.spreadsheet_id
    return spreadsheet


def credentials_to_dict(creds: Credentials):
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def get_active_credentials_json(request, log_action=None):
    creds_json = request.session.get("credentials")
    if not creds_json:
        return None

    try:
        credentials = Credentials.from_authorized_user_info(
            creds_json, OauthConstants.SCOPES
        )
    except Exception as error:
        if log_action:
            log_action(
                "credentials-parse-failed",
                request,
                level="warning",
                error=str(error),
            )
        request.session.pop("credentials", None)
        return None

    if credentials.expired:
        if not credentials.refresh_token:
            if log_action:
                log_action(
                    "credentials-expired",
                    request,
                    level="warning",
                )
            request.session.pop("credentials", None)
            return None

        try:
            credentials.refresh(GoogleAuthRequest())
            request.session["credentials"] = credentials_to_dict(credentials)
        except Exception as error:
            if log_action:
                log_action(
                    "credential-refresh-failed",
                    request,
                    level="warning",
                    error=str(error),
                )
            request.session.pop("credentials", None)
            return None

    if not credentials.valid:
        if log_action:
            log_action(
                "credentials-invalid",
                request,
                level="warning",
            )
        request.session.pop("credentials", None)
        return None

    return request.session.get("credentials")


def logout_user(request, log_action=None):
    if log_action:
        log_action("logout-requested", request)

    creds = request.session.get("credentials")
    if creds:
        token = creds.get("token")
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            if log_action:
                log_action(
                    "logout-complete",
                    request,
                    status_code=response.status_code,
                )
        except Exception as e:
            if log_action:
                log_action(
                    "logout-revoke-failed",
                    request,
                    level="error",
                    error=str(e),
                )

    request.session.flush()
    django_logout(request)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleCollectedView(View, LoggingMixin):
    def post(self, request):
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        if body.get("demo"):
            self.log_action("collection-updated", request, **body)
            return JsonResponse({"status": "success"})

        raw_creds = request.session.get("credentials")
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            if raw_creds:
                creds_json = raw_creds
                self.log_action(
                    "using-stored-credentials",
                    request,
                    level="warning",
                    http_method="POST",
                    endpoint="toggle-collected",
                )
            else:
                self.log_action(
                    "missing-credentials",
                    request,
                    level="warning",
                    http_method="POST",
                    endpoint="toggle-collected",
                )
                return redirect("oauth_login")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            self.log_action(
                "invalid-payload",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-collected",
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-collected",
                error=str(error),
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                },
                status=503,
            )

        amiibo_id = data.get("amiibo_id")
        action = data.get("action")

        if not amiibo_id or action not in {"collect", "uncollect"}:
            self.log_action(
                "missing-parameters",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-collected",
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Both amiibo_id and a valid action are required.",
                },
                status=400,
            )

        try:
            service = AmiiboService(
                google_sheet_client_manager=google_sheet_client_manager
            )
            success = service.toggle_collected(amiibo_id, action)

            if not success:
                self.log_action(
                    "amiibo-not-found",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                )
                return JsonResponse({"status": "not found"}, status=404)

            self.log_action(
                "collection-updated",
                request,
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-collected",
                error=str(error),
            )
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )

        except Exception as e:
            self.log_action(
                "toggle-error",
                request,
                level="error",
                amiibo_id=amiibo_id,
                action=action,
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleFavoriteView(View, LoggingMixin):
    """Toggle the Favorite flag for an amiibo in the user's Google Sheet.

    Mirrors ToggleCollectedView; the amiibo_id is the sheet key
    (head + gameSeries + tail) and the action is 'favorite' / 'unfavorite'.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            self.log_action(
                "invalid-payload",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-favorite",
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        if data.get("demo"):
            self.log_action("favorite-updated", request, **data)
            return JsonResponse({"status": "success"})

        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            self.log_action(
                "missing-credentials",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-favorite",
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Please sign in to favorite amiibo.",
                    "action_required": "reauth_required",
                },
                status=401,
            )

        amiibo_id = data.get("amiibo_id")
        action = data.get("action")

        if not amiibo_id or action not in {"favorite", "unfavorite"}:
            self.log_action(
                "missing-parameters",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-favorite",
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Both amiibo_id and a valid action are required.",
                },
                status=400,
            )

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)

            service = AmiiboService(
                google_sheet_client_manager=google_sheet_client_manager
            )
            success = service.toggle_favorite(amiibo_id, action)

            if not success:
                self.log_action(
                    "amiibo-not-found",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                )
                return JsonResponse({"status": "not found"}, status=404)

            self.log_action(
                "favorite-updated",
                request,
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-favorite",
                error=str(error),
            )
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )

        except Exception as e:
            self.log_action(
                "favorite-error",
                request,
                level="error",
                amiibo_id=amiibo_id,
                action=action,
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


class FavoritesAPIView(View, LoggingMixin):
    """Return the signed-in user's favorited amiibo IDs for lazy hydration.

    Used by the public AmiiboDex page to fill in hearts after load without
    blocking the catalog render. Always responds 200 so the catalog keeps
    working even when the user is logged out or Sheets is unavailable.
    """

    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            return JsonResponse({"authenticated": False, "favorites": []})

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
            service = AmiiboService(
                google_sheet_client_manager=google_sheet_client_manager
            )
            favorite_status = service.get_favorite_status()
            favorites = [
                amiibo_id
                for amiibo_id, value in favorite_status.items()
                if value == "1"
            ]
            return JsonResponse({"authenticated": True, "favorites": favorites})
        except Exception as error:
            self.log_action(
                "favorites-fetch-failed",
                request,
                level="warning",
                endpoint="favorites-api",
                error=str(error),
            )
            return JsonResponse({"authenticated": True, "favorites": [], "error": True})


def _safe_next_url(request, candidate):
    """Return candidate if it is a safe same-host relative redirect, else None.

    Why: prevents an attacker from crafting /oauth-login/?next=https://evil.com
    to phish users after a successful Google login.
    """
    if not candidate:
        return None
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def _request_hostname(request):
    parsed_host = urlsplit(f"//{request.get_host()}")
    return (parsed_host.hostname or "").lower()


def oauth_redirect_uri_for_request(request):
    """Return the Google OAuth callback URL for this environment."""
    hostname = _request_hostname(request)

    if hostname in LOCAL_OAUTH_HOSTS:
        redirect_uri = request.build_absolute_uri(reverse("oauth2callback"))
        if redirect_uri.startswith("http://") or getattr(settings, "DEBUG", False):
            os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
        return redirect_uri

    return OauthConstants.configured_redirect_uri()


class OAuthView(View, LoggingMixin):
    def get(self, request):
        next_url = _safe_next_url(request, request.GET.get("next"))

        creds_json = get_active_credentials_json(request, self.log_action)
        if creds_json:
            return redirect(next_url or "amiibo_list")

        logout_user(request, self.log_action)

        if next_url:
            request.session["oauth_next"] = next_url
        else:
            request.session.pop("oauth_next", None)

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=oauth_redirect_uri_for_request(request),
            autogenerate_code_verifier=True,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        request.session["oauth_state"] = state
        request.session["oauth_code_verifier"] = flow.code_verifier

        return redirect(auth_url)


class OAuthCallbackView(View, LoggingMixin):
    def get(self, request):
        request_state = request.GET.get("state")
        oauth_state = request.session.get("oauth_state")
        oauth_code_verifier = request.session.get("oauth_code_verifier")
        oauth_next = _safe_next_url(request, request.session.pop("oauth_next", None))
        error = request.GET.get("error")
        authorization_code = request.GET.get("code")

        # If Google returned an explicit error or no auth code, send the user back
        # through the OAuth login flow instead of raising an exception.
        if error or not authorization_code:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        # If the state is missing from the session (e.g., a new browser session) try to
        # recover using the callback payload before forcing users through a second
        # authorization prompt. Still require the provided state to match what we last
        # issued when available to avoid unnecessary re-auth redirects.
        if oauth_state and request_state and request_state != oauth_state:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        if not oauth_state:
            if not request_state:
                request.session.pop("oauth_code_verifier", None)
                return redirect("oauth_login")
            oauth_state = request_state

        if not oauth_code_verifier:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=oauth_redirect_uri_for_request(request),
            state=oauth_state,
            code_verifier=oauth_code_verifier,
            autogenerate_code_verifier=False,
        )

        try:
            flow.fetch_token(authorization_response=request.build_absolute_uri())
        except Warning as scope_warning:
            self.log_action(
                "scope-warning", request, level="warning", warning=str(scope_warning)
            )

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    flow.fetch_token(
                        authorization_response=request.build_absolute_uri()
                    )
            except (InvalidGrantError, OAuth2Error, Warning):
                request.session.pop("oauth_state", None)
                request.session.pop("oauth_code_verifier", None)
                return redirect("oauth_login")

        except (InvalidGrantError, OAuth2Error):
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        credentials = flow.credentials

        required_scopes = set(OauthConstants.SCOPES)
        granted_scopes = set(credentials.scopes or [])

        if not required_scopes.issubset(granted_scopes):
            self.log_action(
                "missing-scopes",
                request,
                level="warning",
                required_scopes=list(required_scopes),
                granted_scopes=list(granted_scopes),
            )

            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            request.session.pop("credentials", None)
            request.session.pop("user_name", None)
            request.session.pop("user_email", None)

            return redirect("oauth_login")

        # Clear any stale session data before persisting new account details
        request.session.pop("credentials", None)
        request.session.pop("user_name", None)
        request.session.pop("user_email", None)

        request.session.pop("oauth_state", None)
        request.session.pop("oauth_code_verifier", None)
        request.session["credentials"] = credentials_to_dict(credentials)

        user_service = googleapiclient.discovery.build(
            "oauth2", "v2", credentials=credentials
        )
        user_info = user_service.userinfo().get().execute()

        request.session["user_name"] = user_info.get("name")
        request.session["user_email"] = user_info.get("email")

        try:
            manager = build_sheet_client_manager(request)
            ensure_spreadsheet_session(request, manager)
        except GoogleSheetsError as error:
            # Handle Google Sheets errors gracefully with user-friendly messages
            self.log_action(
                "spreadsheet-init-failed",
                request,
                level="error",
                error=str(error),
                error_type=type(error).__name__,
            )

            # Clear OAuth session data since authentication failed
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            request.session.pop("credentials", None)
            request.session.pop("user_name", None)
            request.session.pop("user_email", None)

            # Store error information in session for display on index page
            request.session["oauth_error"] = {
                "message": error.user_message,
                "action_required": error.action_required,
                "is_retryable": error.is_retryable,
            }

            return redirect("index")
        except Exception as error:
            # Handle unexpected errors
            self.log_action(
                "spreadsheet-init-failed",
                request,
                level="error",
                error=str(error),
                error_type=type(error).__name__,
            )

            # Clear OAuth session data
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            request.session.pop("credentials", None)
            request.session.pop("user_name", None)
            request.session.pop("user_email", None)

            # Store generic error message
            request.session["oauth_error"] = {
                "message": "An unexpected error occurred during login. Please try again.",
                "action_required": "retry",
                "is_retryable": True,
            }

            return redirect("index")

        # New-vs-returning users are derived from user_hash in Grafana LogQL
        # (e.g. `count by (user_hash)` windowed over 24h vs 30d). No DB lookup
        # happens here — the app has no persistent user store.
        self.log_action("login-success", request)

        return redirect(oauth_next or "amiibo_list")


class LogoutView(View, LoggingMixin):
    def get(self, request):
        logout_user(request, self.log_action)
        return redirect("index")


class AmiiboListView(View, LoggingMixin, AmiiboLocalFetchMixin):
    def _render_error_view(self, request, error, user_name):
        """
        Render the amiibo view with an error modal displayed.
        Falls back to displaying amiibos from the API in read-only mode.

        Args:
            request: The HTTP request
            error: The GoogleSheetsError exception
            user_name: The user's name

        Returns:
            Rendered template with error information and fallback data
        """
        self.log_action(
            "sheets-error",
            request,
            level="error",
            endpoint="amiibo-list",
            error=str(error),
        )

        # Try to fetch amiibos from the local database as fallback
        try:
            amiibos = filter_public_amiibos(self._fetch_local_amiibos())
            available_types = sorted(
                {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
            )

            # Mark all as uncollected since we can't read from sheets
            for amiibo in amiibos:
                amiibo["collected"] = False
                amiibo["favorite"] = False
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

            # Sort and group amiibos
            sorted_amiibos = sorted(
                amiibos, key=lambda x: (x.get("amiiboSeries", ""), x.get("name", ""))
            )
            grouped_amiibos = defaultdict(list)
            for amiibo in sorted_amiibos:
                grouped_amiibos[amiibo.get("amiiboSeries", "Unknown")].append(amiibo)

            enriched_groups = []
            for series, amiibo_list in grouped_amiibos.items():
                enriched_groups.append(
                    {
                        "series": series,
                        "list": amiibo_list,
                        "collected_count": 0,
                        "total_count": len(amiibo_list),
                    }
                )

        except Exception as fetch_error:
            self.log_action(
                "fallback-fetch-failed",
                request,
                level="warning",
                error=str(fetch_error),
            )
            sorted_amiibos = []
            available_types = []
            enriched_groups = []

        # Prepare context for error display
        context = {
            "amiibos": sorted_amiibos,
            "dark_mode": False,
            "user_name": user_name,
            "grouped_amiibos": enriched_groups,
            "amiibo_types": [
                {"name": amiibo_type, "ignored": False}
                for amiibo_type in available_types
            ],
            "rate_limited": False,
            "rate_limit_wait_seconds": 0,
            "error": {
                "message": error.user_message,
                "action_required": error.action_required,
                "is_retryable": error.is_retryable,
            },
        }

        # Special handling for rate limit errors
        if isinstance(error, RateLimitError):
            context["rate_limited"] = True
            context["rate_limit_wait_seconds"] = error.retry_after

        return render(request, "tracker/amiibos.html", context)

    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            return redirect("oauth_login")

        user_name = request.session.get("user_name", "User")

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            # Handle errors that occur during spreadsheet initialization
            return self._render_error_view(request, error, user_name)
        service = AmiiboService(google_sheet_client_manager=google_sheet_client_manager)
        config = GoogleSheetConfigManager(
            google_sheet_client_manager=google_sheet_client_manager
        )

        try:
            amiibos = service.fetch_amiibos()
            available_types = sorted(
                {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
            )

            dark_mode = config.is_dark_mode()
            ignored_types = config.get_ignored_types(available_types)

            # Seed only non-ignored amiibos to preserve prior seeding behavior.
            service.seed_new_amiibos(
                [a for a in amiibos if a.get("type") not in ignored_types]
            )
            collected_status, favorite_status = (
                service.get_collected_and_favorite_status()
            )

            for amiibo in amiibos:
                amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
                amiibo["collected"] = collected_status.get(amiibo_id) == "1"
                amiibo["favorite"] = favorite_status.get(amiibo_id) == "1"
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

            sorted_amiibos = sorted(
                amiibos, key=lambda x: (x["amiiboSeries"], x["name"])
            )
            grouped_amiibos = defaultdict(list)
            for amiibo in sorted_amiibos:
                grouped_amiibos[amiibo["amiiboSeries"]].append(amiibo)

            # Ship all amiibos to the client; the client owns the type filter.
            # Group counts reflect the initial (non-ignored) visible set.
            enriched_groups = []
            visible_total = 0
            visible_collected = 0
            for series, group_amiibos in grouped_amiibos.items():
                visible = [
                    a for a in group_amiibos if a.get("type") not in ignored_types
                ]
                total = len(visible)
                collected = sum(1 for a in visible if a["collected"])
                enriched_groups.append(
                    {
                        "series": series,
                        "list": group_amiibos,
                        "collected_count": collected,
                        "total_count": total,
                    }
                )
                visible_total += total
                visible_collected += collected

            self.log_action(
                "render-collection",
                request,
                total_amiibos=visible_total,
                collected_amiibos=visible_collected,
                grouped_series=len(enriched_groups),
                ignored_types=len(ignored_types),
                dark_mode=dark_mode,
            )

            return render(
                request,
                "tracker/amiibos.html",
                {
                    "amiibos": sorted_amiibos,
                    "dark_mode": dark_mode,
                    "user_name": user_name,
                    "grouped_amiibos": enriched_groups,
                    "amiibo_types": [
                        {"name": amiibo_type, "ignored": amiibo_type in ignored_types}
                        for amiibo_type in available_types
                    ],
                    "ignored_types": list(ignored_types),
                    "rate_limited": False,
                    "rate_limit_wait_seconds": 0,
                },
            )

        except GoogleSheetsError as error:
            # Handle our custom exceptions with user-friendly error modal
            return self._render_error_view(request, error, user_name)

        except APIError as error:
            # Handle any remaining APIError exceptions
            if is_rate_limit_error(error):
                # Convert to our custom exception for consistent handling
                rate_limit_error = RateLimitError(
                    retry_after=retry_after_seconds(error)
                )
                return self._render_error_view(request, rate_limit_error, user_name)

            # For other API errors, re-raise to let Django handle them
            self.log_action(
                "unhandled-api-error",
                request,
                level="error",
                error=str(error),
            )
            raise


@method_decorator(csrf_exempt, name="dispatch")
class ToggleDarkModeView(View, LoggingMixin):
    def post(self, request):
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        if body.get("demo"):
            self.log_action("dark-mode-updated", request, **body)
            return JsonResponse({"status": "success"})

        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            self.log_action(
                "missing-credentials",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-dark-mode",
            )
            return redirect("oauth_login")

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)

            data = json.loads(request.body)
            enable_dark = data.get("dark_mode", True)

            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_dark_mode(enable_dark)

            self.log_action(
                "dark-mode-updated",
                request,
                dark_mode=enable_dark,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-dark-mode",
                error=str(error),
            )
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    endpoint="toggle-dark-mode",
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )
        except Exception as e:
            self.log_action(
                "dark-mode-error",
                request,
                level="error",
                endpoint="toggle-dark-mode",
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleTypeFilterView(View, LoggingMixin):
    def post(self, request):
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        if body.get("demo"):
            self.log_action("type-filter-updated", request, **body)
            return JsonResponse({"status": "success"})

        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            self.log_action(
                "missing-credentials",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return redirect("oauth_login")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            self.log_action(
                "invalid-payload",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-type-filter",
                error=str(error),
            )
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        amiibo_type = data.get("type")
        ignore = data.get("ignore", True)

        if not amiibo_type:
            self.log_action(
                "missing-parameters",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return JsonResponse(
                {"status": "error", "message": "Missing type"}, status=400
            )

        try:
            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_ignore_type(amiibo_type, ignore)

            self.log_action(
                "type-filter-updated",
                request,
                amiibo_type=amiibo_type,
                ignore=ignore,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_action(
                "sheets-error",
                request,
                level="error",
                endpoint="toggle-type-filter",
                error=str(error),
            )
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    endpoint="toggle-type-filter",
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )
        except Exception as e:
            self.log_action(
                "type-filter-error",
                request,
                level="error",
                endpoint="toggle-type-filter",
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


class IndexView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("amiibo_list")

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Welcome to Amiibo Tracker", suffix="")
        seo.set_description(
            "Your one-stop shop for everything Amiibo. Track your collection with Google Sheets, learn about NFC technology, and explore Amiibo history."
        )
        seo.set_type("website")

        # Add WebSite schema with SearchAction
        seo.add_schema("WebSite", generate_website_schema())

        # Add Organization schema
        seo.add_schema("Organization", generate_organization_schema())

        # Surface the latest guides on the homepage so visitors (and AdSense
        # reviewers) immediately see substantial editorial content rather than
        # only the collection tool.
        latest_posts = sorted(
            load_blog_posts(), key=lambda p: p.get("date", ""), reverse=True
        )[:6]
        authors = load_authors()
        for post in latest_posts:
            post["author_data"] = authors.get(post.get("author", DEFAULT_AUTHOR_SLUG))

        # Check for OAuth error from session
        context = seo.build()
        context["latest_posts"] = latest_posts
        oauth_error = request.session.pop("oauth_error", None)
        if oauth_error:
            context["error"] = oauth_error

        return render(request, "tracker/index.html", context)


class DemoView(View):
    def get(self, request):
        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Demo", suffix="Amiibo Tracker")
        seo.set_description(
            "Try the Amiibo Tracker demo. See how you can track your collection with Google Sheets integration, filter by series, and manage your Amiibo library."
        )
        seo.set_type("website")

        return render(request, "tracker/demo.html", seo.build())


class PrivacyPolicyView(View):
    def get(self, request):
        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Privacy Policy", suffix="Amiibo Tracker")
        seo.set_description(
            "Learn how Amiibo Tracker handles your data. We use Google authentication and Sheets for collection tracking. Your data stays in your Google Drive."
        )
        seo.set_type("website")

        context = {
            "data_usage": [
                {
                    "item": "Email address",
                    "purpose": "Used to identify your account, keep your session tied to your data, and let you know which Google account is connected.",
                },
                {
                    "item": "Basic profile (name)",
                    "purpose": "Displayed in the app header so you can quickly see which account is active.",
                },
                {
                    "item": "Google Sheets access",
                    "purpose": "Lets Amiibo Tracker create and update your AmiiboCollection sheet so we can store your collection status and dark mode preference without touching any other documents.",
                },
            ]
        }
        context.update(seo.build())

        return render(request, "tracker/privacy.html", context)


class AuthorView(View):
    def get(self, request, slug):
        author = get_author(slug)
        if not author or author.get("slug") != slug:
            raise Http404("Author not found")

        posts = [
            post
            for post in load_blog_posts()
            if post.get("author", DEFAULT_AUTHOR_SLUG) == slug
        ]
        posts = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)

        seo = SEOContext(request)
        seo.set_title(f"{author['name']} ({author['handle']})", suffix="Goozamiibo")
        seo.set_description(author.get("bio", "Goozamiibo author profile."))
        seo.set_type("profile")

        author_url = request.build_absolute_uri()
        seo.add_schema(
            "Person",
            {
                "name": author["name"],
                "alternateName": author.get("handle"),
                "url": author_url,
                "sameAs": [author["x_url"]] if author.get("x_url") else [],
            },
        )

        context = {"author": author, "posts": posts}
        context.update(seo.build())
        return render(request, "tracker/author.html", context)


class AmiiboDatabaseView(
    View, LoggingMixin, AmiiboRemoteFetchMixin, AmiiboLocalFetchMixin
):
    def get(self, request):
        remote_amiibos = self._fetch_remote_amiibos()

        if remote_amiibos:
            amiibos = remote_amiibos
            local_amiibos = self._fetch_local_amiibos()
            self._log_missing_remote_items(local_amiibos, remote_amiibos)
        else:
            amiibos = self._fetch_local_amiibos()

        amiibos = filter_public_amiibos(amiibos)

        if not amiibos:
            return JsonResponse(
                {"status": "error", "message": "Amiibo database unavailable."},
                status=500,
            )

        filtered_amiibos = self._filter_amiibos(amiibos, request)

        if request.GET.get("showusage") is not None and remote_amiibos:
            filtered_amiibos = self._attach_usage_data(filtered_amiibos, remote_amiibos)

        return JsonResponse({"amiibo": filtered_amiibos}, safe=False)

    @staticmethod
    def _filter_amiibos(amiibos: list[dict], request):
        name_filter = request.GET.get("name")
        game_series_filter = request.GET.get("gameseries") or request.GET.get(
            "gameSeries"
        )
        character_filter = request.GET.get("character")

        def matches(value, query):
            return query.lower() in (value or "").lower()

        filtered = []
        for amiibo in amiibos:
            if name_filter and not matches(amiibo.get("name"), name_filter):
                continue
            if game_series_filter and not matches(
                amiibo.get("gameSeries"), game_series_filter
            ):
                continue
            if character_filter and not matches(
                amiibo.get("character"), character_filter
            ):
                continue
            filtered.append(dict(amiibo))

        return filtered

    def _log_missing_remote_items(self, local_amiibos: list[dict], remote_amiibos):
        local_ids = {
            f"{amiibo.get('head', '')}{amiibo.get('tail', '')}"
            for amiibo in local_amiibos
            if amiibo.get("head") and amiibo.get("tail")
        }

        missing_remote = [
            amiibo
            for amiibo in remote_amiibos
            if amiibo.get("head")
            and amiibo.get("tail")
            and f"{amiibo.get('head')}{amiibo.get('tail')}" not in local_ids
        ]

        if missing_remote:
            self.log_warning(
                "amiibo-database-missing-items",
                missing_count=len(missing_remote),
                missing_ids=[
                    f"{amiibo.get('name', 'unknown')} ({amiibo.get('head')}{amiibo.get('tail')})"
                    for amiibo in missing_remote
                ],
            )

    @staticmethod
    def _attach_usage_data(amiibos: list[dict], remote_amiibos: list[dict]):
        usage_keys = ["gamesSwitch", "games3DS", "gamesWiiU"]
        remote_lookup = {
            f"{amiibo.get('head')}{amiibo.get('tail')}": amiibo
            for amiibo in remote_amiibos
            if amiibo.get("head") and amiibo.get("tail")
        }

        enriched = []
        for amiibo in amiibos:
            amiibo_id = f"{amiibo.get('head', '')}{amiibo.get('tail', '')}"
            remote_match = remote_lookup.get(amiibo_id, {})
            amiibo_with_usage = dict(amiibo)
            for key in usage_keys:
                if key in remote_match:
                    amiibo_with_usage[key] = remote_match[key]
            enriched.append(amiibo_with_usage)

        return enriched


class BlogListView(View, LoggingMixin):
    def get(self, request):
        # Load blog posts from JSON file
        posts = load_blog_posts()
        authors = load_authors()
        for post in posts:
            post["author_data"] = authors.get(post.get("author", DEFAULT_AUTHOR_SLUG))
        # Sort by date (newest first)
        posts = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)

        self.log_action(
            "blog-list-view",
            request,
            total_posts=len(posts),
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Amiibo Collector Guides", suffix="Goozamiibo")
        seo.set_description(
            "Source-checked Goozamiibo guides for amiibo compatibility, collecting, display, rarity, NFC basics, and official figure verification."
        )
        seo.set_type("website")

        # Add Organization schema
        seo.add_schema("Organization", generate_organization_schema())

        context = {"posts": posts}
        context.update(seo.build())

        return render(request, "tracker/blog_list.html", context)


class BlogPostView(View, LoggingMixin, AmiiboLocalFetchMixin):
    def get(self, request, slug):
        # Load blog posts from JSON and find by slug
        posts = load_blog_posts()
        # Sort newest-first so prev/next are stable
        posts = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)
        post = next((p for p in posts if p.get("slug") == slug), None)

        if not post:
            self.log_action(
                "blog-post-not-found",
                request,
                level="warning",
                slug=slug,
            )
            raise Http404("Blog post not found")

        idx = next(i for i, p in enumerate(posts) if p.get("slug") == slug)
        prev_post = posts[idx + 1] if idx + 1 < len(posts) else None
        next_post = posts[idx - 1] if idx > 0 else None
        author = get_author(post.get("author", DEFAULT_AUTHOR_SLUG))
        author_url = (
            request.build_absolute_uri(f"/authors/{author['slug']}/")
            if author
            else None
        )

        # Rough read-time estimate from text content
        import re as _re

        raw = post.get("content") or ""
        if isinstance(raw, str) and raw != "dynamic":
            words = len(_re.findall(r"\w+", _re.sub(r"<[^>]+>", " ", raw)))
            read_minutes = max(1, round(words / 230))
        else:
            read_minutes = None

        self.log_action(
            "blog-post-view",
            request,
            slug=slug,
            title=post.get("title"),
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title(post.get("title"), suffix="Amiibo Blog")

        # Check if content is dynamic
        is_dynamic = post.get("content") == "dynamic"

        # Generate description from excerpt or content
        description = post.get("excerpt") or generate_meta_description(
            post.get("content")
            if not is_dynamic
            else "Browse the complete catalog of all released Amiibo figures, sorted by newest to oldest."
        )
        seo.set_description(description)
        seo.set_type("article")

        # Set OG image if featured_image exists
        if post.get("featured_image"):
            from django.templatetags.static import static

            image_url = static(post["featured_image"])
            seo.set_og_image(image_url)

        # Add Article schema
        post_url = request.build_absolute_uri()
        seo.add_schema(
            "Article",
            generate_article_schema(
                title=post.get("title"),
                description=description,
                url=post_url,
                date_published=post.get("date"),  # Already in ISO format (YYYY-MM-DD)
                author=author["name"] if author else "Sina",
                author_url=author_url,
                author_same_as=author.get("x_url") if author else None,
                author_alternate_name=author.get("handle") if author else None,
                publisher="Goozamiibo",
            ),
        )

        # Add BreadcrumbList schema
        breadcrumbs = [
            ("Home", request.build_absolute_uri("/")),
            ("Blog", request.build_absolute_uri("/blog/")),
            (post.get("title"), post_url),
        ]
        seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

        comments = load_comments(
            BLOG_COMMENTS_COLLECTION,
            "slug",
            slug,
            f"comments:blog:{slug}",
            logger=self,
            request=request,
            log_event="blog-comments-load-failed",
        )
        comment_banner = comment_banner_for(request.GET.get("comment"))

        context = {
            "post": post,
            "author": author,
            "author_url": author_url,
            "prev_post": prev_post,
            "next_post": next_post,
            "read_minutes": read_minutes,
            "comments": comments,
            "comment_banner": comment_banner,
            "current_user_email": request.session.get("user_email"),
            "current_user_name": request.session.get("user_name"),
            "comment_body_max_len": COMMENT_BODY_MAX_LEN,
        }
        context.update(seo.build())

        # Handle dynamic content for posts with content="dynamic"
        if is_dynamic:
            try:
                amiibos = filter_public_amiibos(self._fetch_local_amiibos())

                # Add formatted release date and amiibo_id for each amiibo
                for amiibo in amiibos:
                    amiibo["display_release"] = AmiiboService._format_release_date(
                        amiibo.get("release")
                    )
                    # Create amiibo_id in head-tail format for URL
                    amiibo["amiibo_id"] = (
                        f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"
                    )

                    # Extract the earliest release date for sorting
                    release_dates = amiibo.get("release", {})
                    earliest_date = None
                    for region in ["na", "jp", "eu", "au"]:
                        date_str = release_dates.get(region)
                        if date_str:
                            try:
                                from datetime import datetime

                                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                                if earliest_date is None or date_obj < earliest_date:
                                    earliest_date = date_obj
                            except (ValueError, TypeError):
                                pass
                    amiibo["earliest_release"] = earliest_date

                # Sort by earliest release date (newest first), then by name
                sorted_amiibos = sorted(
                    amiibos,
                    key=lambda x: (
                        x["earliest_release"] is None,  # Put None dates at end
                        x["earliest_release"] if x["earliest_release"] else "",
                        x.get("name", ""),
                    ),
                    reverse=True,  # Newest first
                )

                # Implement pagination (50 items per page)
                page = request.GET.get("page", 1)
                paginator = Paginator(sorted_amiibos, 50)

                try:
                    amiibos_page = paginator.page(page)
                except PageNotAnInteger:
                    amiibos_page = paginator.page(1)
                except EmptyPage:
                    amiibos_page = paginator.page(paginator.num_pages)

                context["amiibos"] = amiibos_page
                context["total_count"] = len(sorted_amiibos)

                self.log_action(
                    "blog-dynamic-content-loaded",
                    request,
                    slug=slug,
                    amiibo_count=len(sorted_amiibos),
                )
            except Exception as e:
                self.log_action(
                    "blog-dynamic-content-error",
                    request,
                    level="error",
                    slug=slug,
                    error=str(e),
                )
                context["amiibos"] = []
                context["total_count"] = 0
                context["error"] = True

        return render(request, "tracker/blog_post.html", context)


class AmiibodexView(View, LoggingMixin, AmiiboLocalFetchMixin):
    """View for the Amiibodex page - a comprehensive list of all released amiibo."""

    def get(self, request):
        self.log_action(
            "amiibodex-view",
            request,
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Amiibodex", suffix="Complete Amiibo Database")

        description = "Browse the complete catalog of all released Amiibo figures, sorted by newest to oldest. A comprehensive, always up-to-date database of every amiibo ever released."
        seo.set_description(description)
        seo.set_type("website")

        # Add BreadcrumbList schema
        amiibodex_url = request.build_absolute_uri()
        breadcrumbs = [
            ("Home", request.build_absolute_uri("/")),
            ("Amiibodex", amiibodex_url),
        ]
        seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

        context = {}
        context.update(seo.build())

        try:
            # Fetch from local database which includes scraped + backfilled amiibos
            amiibos = filter_public_amiibos(self._fetch_local_amiibos())

            # Add formatted release date and amiibo_id for each amiibo
            for amiibo in amiibos:
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )
                # Create amiibo_id in head-tail format for URL
                amiibo["amiibo_id"] = (
                    f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"
                )
                # Sheet key (head + gameSeries + tail) used to match favorites,
                # which are stored per-user in the Google Sheet.
                amiibo["favorite_id"] = (
                    f"{amiibo.get('head', '')}"
                    f"{amiibo.get('gameSeries', '')}"
                    f"{amiibo.get('tail', '')}"
                )

                # Extract the earliest release date for sorting
                release_dates = amiibo.get("release", {})
                earliest_date = None
                for region in ["na", "jp", "eu", "au"]:
                    date_str = release_dates.get(region)
                    if date_str:
                        try:
                            from datetime import datetime

                            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                            if earliest_date is None or date_obj < earliest_date:
                                earliest_date = date_obj
                        except (ValueError, TypeError):
                            pass
                amiibo["earliest_release"] = earliest_date

                # Determine if amiibo is upcoming
                from datetime import datetime

                today = datetime.now().date()
                is_upcoming = False

                if earliest_date is None:
                    # No release date = upcoming/TBA
                    is_upcoming = True
                elif earliest_date.date() > today:
                    # Future release date = upcoming
                    is_upcoming = True

                amiibo["is_upcoming"] = is_upcoming

            # Sort by earliest release date (newest first), then by name
            sorted_amiibos = sorted(
                amiibos,
                key=lambda x: (
                    x["earliest_release"] is None,  # Put None dates at end
                    x["earliest_release"] if x["earliest_release"] else "",
                    x.get("name", ""),
                ),
                reverse=True,  # Newest first
            )

            context["amiibos"] = sorted_amiibos
            context["total_count"] = len(sorted_amiibos)

            self.log_action(
                "amiibodex-content-loaded",
                request,
                amiibo_count=len(sorted_amiibos),
            )
        except Exception as e:
            self.log_action(
                "amiibodex-content-error",
                request,
                level="error",
                error=str(e),
            )
            context["amiibos"] = []
            context["total_count"] = 0
            context["error"] = True

        return render(request, "tracker/amiibodex.html", context)


class AmiiboDetailView(View, LoggingMixin, AmiiboLocalFetchMixin):
    """
    View for displaying individual amiibo details.
    URL pattern: /blog/number-released/amiibo/<head>-<tail>/
    """

    def get(self, request, amiibo_id):
        # Parse amiibo_id (format: head-tail)
        try:
            head, tail = amiibo_id.split("-")
            if len(head) != 8 or len(tail) != 8:
                raise ValueError("Invalid amiibo ID format")
        except (ValueError, AttributeError):
            self.log_action(
                "amiibo-detail-invalid-id",
                request,
                level="warning",
                amiibo_id=amiibo_id,
            )
            raise Http404("Invalid amiibo ID")

        # Fetch all amiibos and find the matching one
        try:
            amiibos = filter_public_amiibos(self._fetch_local_amiibos())
            amiibo = next(
                (a for a in amiibos if a.get("head") == head and a.get("tail") == tail),
                None,
            )

            if not amiibo:
                self.log_action(
                    "amiibo-detail-not-found",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                )
                raise Http404("Amiibo not found")

            # Add formatted release dates
            amiibo["display_release"] = AmiiboService._format_release_date(
                amiibo.get("release")
            )

            # Format regional release dates
            release_dates = amiibo.get("release", {})
            regional_releases = []
            region_names = {
                "na": "North America",
                "jp": "Japan",
                "eu": "Europe",
                "au": "Australia",
            }

            for region_code, region_name in region_names.items():
                date_str = release_dates.get(region_code)
                if date_str:
                    try:
                        from datetime import datetime

                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%B %d, %Y")
                        regional_releases.append(
                            {"region": region_name, "date": formatted_date}
                        )
                    except (ValueError, TypeError):
                        pass

            # Get character description
            description = self._get_character_description(amiibo)

            # Build SEO context
            seo = SEOContext(request)
            amiibo_name = amiibo.get("name", "Unknown Amiibo")
            seo.set_title(f"{amiibo_name} Details", suffix="Amiibo Tracker")

            # Generate description from amiibo data
            game_series = amiibo.get("gameSeries", "")
            amiibo_series = amiibo.get("amiiboSeries", "")
            release_info = amiibo.get("display_release", "")
            meta_description = f"{amiibo_name} amiibo from {game_series}. Part of the {amiibo_series} series."
            if release_info:
                meta_description += f" Released {release_info}."
            seo.set_description(meta_description[:155])

            seo.set_type("product")

            # Set OG image if available
            if amiibo.get("image"):
                seo.set_og_image(amiibo["image"])

            # Add BlogPosting schema (wiki-style informational content)
            product_url = request.build_absolute_uri()
            earliest_release = None
            for region in ["na", "jp", "eu", "au"]:
                date_str = release_dates.get(region)
                if date_str:
                    earliest_release = date_str
                    break

            seo.add_schema(
                "BlogPosting",
                generate_blog_posting_schema(
                    name=amiibo_name,
                    description=description or meta_description,
                    image=amiibo.get("image", ""),
                    url=product_url,
                    date_published=earliest_release,
                    author="Amiibo Tracker",
                    publisher="Amiibo Tracker",
                ),
            )

            # Add BreadcrumbList schema
            breadcrumbs = [
                ("Home", request.build_absolute_uri("/")),
                ("Blog", request.build_absolute_uri("/blog/")),
                ("All Amiibo", request.build_absolute_uri("/blog/number-released/")),
                (amiibo_name, product_url),
            ]
            seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

            # Related amiibo from the same series — adds internal links and
            # unique, less templated content to every detail page (helps both
            # search discovery and AdSense content-value review).
            related_same_series = []
            related_same_game = []
            target_amiibo_series = amiibo.get("amiiboSeries")
            target_game_series = amiibo.get("gameSeries")
            for other in amiibos:
                if other.get("head") == head and other.get("tail") == tail:
                    continue
                other_head = other.get("head", "")
                other_tail = other.get("tail", "")
                if not other_head or not other_tail:
                    continue
                entry = {
                    "name": other.get("name", "Unknown"),
                    "image": other.get("image", ""),
                    "url": f"/blog/number-released/amiibo/{other_head}-{other_tail}/",
                }
                if (
                    target_amiibo_series
                    and other.get("amiiboSeries") == target_amiibo_series
                ):
                    related_same_series.append(entry)
                elif (
                    target_game_series and other.get("gameSeries") == target_game_series
                ):
                    related_same_game.append(entry)
            related_amiibo = (related_same_series + related_same_game)[:8]

            # Build an FAQ from real attributes only (no fabricated facts).
            faqs = []
            amiibo_type = amiibo.get("type")
            if amiibo_type:
                faqs.append(
                    {
                        "question": f"What type of amiibo is {amiibo_name}?",
                        "answer": f"{amiibo_name} is a {amiibo_type.lower()} amiibo.",
                    }
                )
            if target_game_series:
                faqs.append(
                    {
                        "question": f"What game series is the {amiibo_name} amiibo from?",
                        "answer": f"The {amiibo_name} amiibo is from the {target_game_series} series.",
                    }
                )
            if target_amiibo_series:
                faqs.append(
                    {
                        "question": f"Which amiibo series does {amiibo_name} belong to?",
                        "answer": f"{amiibo_name} is part of the {target_amiibo_series} amiibo series.",
                    }
                )
            if regional_releases:
                release_parts = ", ".join(
                    f"{r['region']} on {r['date']}" for r in regional_releases
                )
                faqs.append(
                    {
                        "question": f"When was the {amiibo_name} amiibo released?",
                        "answer": f"The {amiibo_name} amiibo was released in {release_parts}.",
                    }
                )

            if faqs:
                seo.add_schema(
                    "FAQPage",
                    {
                        "mainEntity": [
                            {
                                "@type": "Question",
                                "name": f["question"],
                                "acceptedAnswer": {
                                    "@type": "Answer",
                                    "text": f["answer"],
                                },
                            }
                            for f in faqs
                        ]
                    },
                )

            # Comments load asynchronously via AmiiboCommentsView so the
            # Firestore round-trip never blocks this page's render.
            context = {
                "amiibo": amiibo,
                "regional_releases": regional_releases,
                "description": description,
                "related_amiibo": related_amiibo,
                "faqs": faqs,
            }
            context.update(seo.build())

            self.log_action(
                "amiibo-detail-view",
                request,
                amiibo_id=amiibo_id,
                amiibo_name=amiibo.get("name"),
            )

            return render(request, "tracker/amiibo_detail.html", context)

        except Exception as e:
            self.log_action(
                "amiibo-detail-error",
                request,
                level="error",
                amiibo_id=amiibo_id,
                error=str(e),
            )
            raise

    def _get_character_description(self, amiibo):
        """
        Get character description. First tries to load from JSON file using amiibo name,
        then falls back to character name, then template-based description.
        """
        amiibo_name = amiibo.get("name", "")
        character_name = amiibo.get("character", "")
        game_series = amiibo.get("gameSeries", "")
        amiibo_id = f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"

        # Try to load custom descriptions from JSON file
        descriptions_path = (
            Path(__file__).parent / "data" / "character_descriptions.json"
        )
        if descriptions_path.exists():
            try:
                with open(descriptions_path, "r", encoding="utf-8") as f:
                    descriptions = json.load(f)
                    # Try amiibo id first (disambiguates same-named amiibos from
                    # different series, e.g. Animal Crossing vs Monster Hunter)
                    if amiibo_id in descriptions:
                        return descriptions[amiibo_id]
                    # Then amiibo name (for variant-specific descriptions)
                    if amiibo_name in descriptions:
                        return descriptions[amiibo_name]
                    # Fall back to character name
                    if character_name in descriptions:
                        return descriptions[character_name]
            except Exception as e:
                self.log_warning(
                    "description-load-failed",
                    amiibo_name=amiibo_name,
                    error=str(e),
                )

        # Template-based description (fallback)
        if character_name and game_series:
            return f"{character_name} is a character from the {game_series} series."
        elif character_name:
            return f"{character_name} is featured in this amiibo."
        else:
            return "This amiibo features a character from Nintendo's gaming universe."


class AmiiboCommentsView(View, LoggingMixin):
    """Render the comments block for an amiibo as a standalone HTML fragment.

    The detail page loads this asynchronously so the (Firestore-backed) comment
    fetch never blocks the main page render — the amiibo content paints
    immediately and comments fill in a moment later.
    """

    def get(self, request, amiibo_id):
        comments = load_comments(
            AMIIBO_COMMENTS_COLLECTION,
            "amiibo_id",
            amiibo_id,
            f"comments:amiibo:{amiibo_id}",
            logger=self,
            request=request,
        )
        context = {
            "comments": comments,
            "comment_banner": comment_banner_for(request.GET.get("comment")),
            "current_user_email": request.session.get("user_email"),
            "current_user_name": request.session.get("user_name"),
            "comment_body_max_len": COMMENT_BODY_MAX_LEN,
            "comment_post_url": (f"/blog/number-released/amiibo/{amiibo_id}/comment/"),
            # Send post-login users back to the detail page, not this fragment.
            "comment_login_next": f"/blog/number-released/amiibo/{amiibo_id}/",
            "comment_placeholder": "Share your thoughts...",
            "comment_track_prefix": "comment",
            "comment_btn_class": "action-btn primary",
        }
        return render(request, "tracker/_comments.html", context)


class RobotsTxtView(View):
    """
    Serves the robots.txt file with proper content type.
    """

    def get(self, request):
        robots_path = Path(__file__).parent.parent / "static" / "robots.txt"
        try:
            with open(robots_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HttpResponse(content, content_type="text/plain")
        except FileNotFoundError:
            return HttpResponse("User-agent: *\nAllow: /\n", content_type="text/plain")


class AdsTxtView(View):
    """
    Serves the ads.txt file with proper content type.

    Required at the domain root for Google AdSense to verify authorized
    sellers of the site's ad inventory.
    """

    def get(self, request):
        ads_path = Path(__file__).parent.parent / "static" / "ads.txt"
        try:
            with open(ads_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HttpResponse(content, content_type="text/plain")
        except FileNotFoundError:
            return HttpResponse("", content_type="text/plain")


@method_decorator(csrf_exempt, name="dispatch")
class NintendoScraperAPIView(View, LoggingMixin):
    """
    API endpoint for triggering amiibo scraper (now using amiibo.life).
    Designed for Cloud Scheduler or manual triggering.
    """

    def post(self, request):
        """Trigger the scraper"""
        denial = check_rate_limit(
            request,
            bucket="scrape",
            per_ip_max=3,
            per_ip_window=600,
            global_max=20,
            global_window=3600,
        )
        if denial:
            self.log_action(
                "scraper-api-rate-limited", request, level="warning", reason=denial
            )
            return JsonResponse({"status": "error", "message": denial}, status=429)

        try:
            scraper = AmiiboLifeScraper()
            result = scraper.run(force=True)

            self.log_action(
                "scraper-api-triggered",
                request,
                level="info",
                result=result,
            )

            return JsonResponse(result, status=200)

        except Exception as e:
            self.log_action(
                "scraper-api-error",
                request,
                level="error",
                error=str(e),
            )
            return JsonResponse(
                {"status": "error", "message": str(e)},
                status=500,
            )

    def get(self, request):
        """Health check / info endpoint"""
        return JsonResponse(
            {
                "status": "ready",
                "endpoint": "POST to this URL to trigger scraper",
                "info": "Designed for Google Cloud Scheduler",
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class DailyReportAPIView(View, LoggingMixin):
    """Public on-demand trigger for the daily DAU report email.

    Mirrors NintendoScraperAPIView: plain POST, no auth, fires the
    report_daily_users management command synchronously.
    """

    def post(self, request):
        from django.core.management import call_command

        denial = check_rate_limit(
            request,
            bucket="daily-report",
            per_ip_max=3,
            per_ip_window=600,
            global_max=20,
            global_window=3600,
        )
        if denial:
            self.log_action(
                "daily-report-api-rate-limited", request, level="warning", reason=denial
            )
            return JsonResponse({"status": "error", "message": denial}, status=429)

        try:
            call_command("report_daily_users")
            self.log_action("daily-report-api-triggered", request, level="info")
            return JsonResponse({"status": "ok"}, status=200)
        except Exception as e:
            self.log_action(
                "daily-report-api-error", request, level="error", error=str(e)
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse(
            {
                "status": "ready",
                "endpoint": "POST to this URL to send the daily DAU report",
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class DailyReportTriggerView(View):
    """Cloud Scheduler -> this endpoint -> the report_daily_users command.

    Cloud Run is publicly invokable for the rest of the app, so this endpoint
    must authenticate the caller at the application layer. We verify the OIDC
    JWT that Cloud Scheduler attaches: issuer must be accounts.google.com,
    audience must be our Cloud Run URL, and the email claim must equal the
    scheduler service account this Cloud Run service expects.
    """

    def post(self, request):
        from django.conf import settings as dj_settings
        from django.core.management import call_command
        from google.auth.transport import requests as ga_requests
        from google.oauth2 import id_token

        expected_email = dj_settings.DAILY_REPORT_SCHEDULER_SA_EMAIL
        if not expected_email:
            return JsonResponse(
                {"error": "scheduler-sa-email-not-configured"}, status=503
            )

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "missing-bearer-token"}, status=401)
        token = auth_header[len("Bearer ") :].strip()

        expected_audience = getattr(
            dj_settings, "DAILY_REPORT_EXPECTED_AUDIENCE", ""
        ) or os.environ.get("DAILY_REPORT_EXPECTED_AUDIENCE", "")
        try:
            claims = id_token.verify_oauth2_token(
                token,
                ga_requests.Request(),
                audience=expected_audience or None,
            )
        except ValueError as exc:
            logger.warning("daily-report-oidc-verify-failed: %s", exc)
            return JsonResponse({"error": "invalid-token"}, status=401)

        if claims.get("iss") not in (
            "https://accounts.google.com",
            "accounts.google.com",
        ):
            return JsonResponse({"error": "unexpected-issuer"}, status=401)
        if claims.get("email") != expected_email:
            return JsonResponse({"error": "unexpected-sa"}, status=403)
        if not claims.get("email_verified"):
            return JsonResponse({"error": "email-not-verified"}, status=403)

        try:
            call_command("report_daily_users")
        except Exception as exc:
            logger.exception("daily-report-command-failed")
            return JsonResponse({"error": str(exc)}, status=500)

        return HttpResponse(status=204)


class AmiiboCommentMixin:
    """Page identity for amiibo-detail comments, shared by post + delete views."""

    collection = AMIIBO_COMMENTS_COLLECTION
    key_field = "amiibo_id"
    log_prefix = "comment"

    def resolve_key(self, request, amiibo_id=None, **kwargs):
        import re

        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{8}", amiibo_id or ""):
            raise Http404("Invalid amiibo ID")
        return amiibo_id

    def redirect_to(self, key_value, status):
        return redirect(f"/blog/number-released/amiibo/{key_value}/?comment={status}")

    def cache_key(self, key_value):
        return f"comments:amiibo:{key_value}"


class BlogCommentMixin:
    """Page identity for blog-post comments, shared by post + delete views."""

    collection = BLOG_COMMENTS_COLLECTION
    key_field = "slug"
    log_prefix = "blog-comment"

    def resolve_key(self, request, slug=None, **kwargs):
        posts = load_blog_posts()
        if not any(p.get("slug") == slug for p in posts):
            raise Http404("Blog post not found")
        return slug

    def redirect_to(self, key_value, status):
        return redirect(f"/blog/{key_value}/?comment={status}")

    def cache_key(self, key_value):
        return f"comments:blog:{key_value}"


class PostCommentView(AmiiboCommentMixin, CommentPostView):
    """Create a comment (or reply) on an amiibo detail page."""


class DeleteCommentView(AmiiboCommentMixin, CommentDeleteView):
    """Delete one's own comment on an amiibo detail page."""


class PostBlogCommentView(BlogCommentMixin, CommentPostView):
    """Create a comment (or reply) on a blog post."""


class DeleteBlogCommentView(BlogCommentMixin, CommentDeleteView):
    """Delete one's own comment on a blog post."""
