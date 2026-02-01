import json
import os
import warnings
from collections import defaultdict
from pathlib import Path

import googleapiclient.discovery
import requests
from gspread.exceptions import APIError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from django.contrib.auth import logout as django_logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.helpers import LoggingMixin, AmiiboRemoteFetchMixin
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


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
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)

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


class OAuthView(View, LoggingMixin):
    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if creds_json:
            return redirect("amiibo_list")

        logout_user(request, self.log_action)

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
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
            redirect_uri=OauthConstants.REDIRECT_URI,
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
        except Exception as error:
            self.log_action(
                "spreadsheet-init-failed",
                request,
                level="error",
                error=str(error),
            )
            raise

        self.log_action(
            "login-success",
            request,
            user_name=request.session.get("user_name"),
            user_email=request.session.get("user_email"),
        )

        return redirect("amiibo_list")


class LogoutView(View, LoggingMixin):
    def get(self, request):
        logout_user(request, self.log_action)
        return redirect("index")


class AmiiboListView(View, LoggingMixin):
    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            return redirect("oauth_login")

        user_name = request.session.get("user_name", "User")

        google_sheet_client_manager = build_sheet_client_manager(request, creds_json)
        ensure_spreadsheet_session(request, google_sheet_client_manager)
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
            filtered_amiibos = [
                a for a in amiibos if a.get("type") not in ignored_types
            ]

            service.seed_new_amiibos(filtered_amiibos)
            collected_status = service.get_collected_status()

            for amiibo in filtered_amiibos:
                amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
                amiibo["collected"] = collected_status.get(amiibo_id) == "1"
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

            sorted_amiibos = sorted(
                filtered_amiibos, key=lambda x: (x["amiiboSeries"], x["name"])
            )
            grouped_amiibos = defaultdict(list)
            for amiibo in sorted_amiibos:
                grouped_amiibos[amiibo["amiiboSeries"]].append(amiibo)

            enriched_groups = []
            for series, amiibos in grouped_amiibos.items():
                total = len(amiibos)
                collected = sum(1 for a in amiibos if a["collected"])
                enriched_groups.append(
                    {
                        "series": series,
                        "list": amiibos,
                        "collected_count": collected,
                        "total_count": total,
                    }
                )

            self.log_action(
                "render-collection",
                request,
                total_amiibos=len(sorted_amiibos),
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
                    "rate_limited": False,
                    "rate_limit_wait_seconds": 0,
                },
            )

        except APIError as error:
            if not is_rate_limit_error(error):
                raise

            amiibos = service.fetch_amiibos()
            available_types = sorted(
                {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
            )

            for amiibo in amiibos:
                amiibo["collected"] = False
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

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

            return render(
                request,
                "tracker/amiibos.html",
                {
                    "amiibos": sorted_amiibos,
                    "dark_mode": False,
                    "user_name": user_name,
                    "grouped_amiibos": enriched_groups,
                    "amiibo_types": [
                        {"name": amiibo_type, "ignored": False}
                        for amiibo_type in available_types
                    ],
                    "rate_limited": True,
                    "rate_limit_wait_seconds": retry_after_seconds(error),
                },
            )

            self.log_action(
                "render-collection-rate-limited",
                request,
                total_amiibos=len(sorted_amiibos),
                grouped_series=len(enriched_groups),
                retry_after=retry_after_seconds(error),
            )


@method_decorator(csrf_exempt, name="dispatch")
class ToggleDarkModeView(View, LoggingMixin):
    def post(self, request):
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
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)

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
        return render(request, "tracker/index.html")


class PrivacyPolicyView(View):
    def get(self, request):
        return render(
            request,
            "tracker/privacy.html",
            {
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
            },
        )


class AmiiboDatabaseView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    def get(self, request):
        data, error_response = self._load_local_database()
        if error_response:
            return error_response

        amiibos = data.get("amiibo", []) if isinstance(data, dict) else []
        remote_amiibos = self._fetch_remote_amiibos()

        if remote_amiibos:
            self._log_missing_remote_items(amiibos, remote_amiibos)

        filtered_amiibos = self._filter_amiibos(amiibos, request)

        if request.GET.get("showusage") is not None:
            filtered_amiibos = self._attach_usage_data(filtered_amiibos, remote_amiibos)

        return JsonResponse({"amiibo": filtered_amiibos}, safe=False)

    def _load_local_database(self):
        database_path = Path(__file__).with_name("amiibo_database.json")

        try:
            with database_path.open(encoding="utf-8") as database_file:
                return json.load(database_file), None
        except FileNotFoundError:
            return None, JsonResponse(
                {"status": "error", "message": "Amiibo database unavailable."},
                status=500,
            )
        except json.JSONDecodeError:
            return None, JsonResponse(
                {"status": "error", "message": "Amiibo database is corrupted."},
                status=500,
            )

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
