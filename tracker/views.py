import json
from collections import defaultdict

import googleapiclient.discovery
import requests
from django.contrib.auth import logout as django_logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.helpers import LoggingMixin
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager


@method_decorator(csrf_exempt, name="dispatch")
class ToggleCollectedView(View):
    def post(self, request):
        creds_json = request.session.get("credentials")
        if not creds_json:
            return redirect("oauth_login")

        google_sheet_client_manager = GoogleSheetClientManager(creds_json=creds_json)

        try:
            data = json.loads(request.body)
            amiibo_id = data["amiibo_id"]
            action = data["action"]

            service = AmiiboService(
                google_sheet_client_manager=google_sheet_client_manager
            )
            success = service.toggle_collected(amiibo_id, action)

            if not success:
                return JsonResponse({"status": "not found"}, status=404)

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


class OAuthView(View):
    def get(self, request):
        if request.session.get("credentials"):
            return redirect("amiibo_list")

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        request.session["oauth_state"] = state

        return redirect(auth_url)


class OAuthCallbackView(View):
    def get(self, request):
        def credentials_to_dict(creds):
            return {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes,
            }

        if request.session.get("credentials"):
            return redirect("amiibo_list")

        request_state = request.GET.get("state")
        oauth_state = request.session.get("oauth_state")

        # If the state is missing from the session (e.g., a new browser session) try to
        # recover using the callback payload before forcing users through a second
        # authorization prompt. Still require the provided state to match what we last
        # issued when available to avoid unnecessary re-auth redirects.
        if oauth_state and request_state and request_state != oauth_state:
            return redirect("oauth_login")

        if not oauth_state:
            if not request_state:
                return redirect("oauth_login")
            oauth_state = request_state

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
            state=oauth_state,
        )

        flow.fetch_token(authorization_response=request.build_absolute_uri())

        credentials = flow.credentials

        request.session.pop("oauth_state", None)
        request.session["credentials"] = credentials_to_dict(credentials)

        user_service = googleapiclient.discovery.build(
            "oauth2", "v2", credentials=credentials
        )
        user_info = user_service.userinfo().get().execute()

        request.session["user_name"] = user_info.get("name")
        request.session["user_email"] = user_info.get("email")

        return redirect("amiibo_list")


class LogoutView(View, LoggingMixin):
    def get(self, request):
        creds = request.session.get("credentials")
        if creds:
            token = creds.get("token")
            try:
                response = requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token},
                    headers={"content-type": "application/x-www-form-urlencoded"},
                )
                self.log_info(
                    "successfully logged out", {"status_code": response.status_code}
                )
            except Exception as e:
                print(f"Failed to revoke token: {e}")

        request.session.flush()
        django_logout(request)
        return redirect("index")


class AmiiboListView(View):
    def get(self, request):
        creds_json = request.session.get("credentials")
        if not creds_json:
            return redirect("oauth_login")

        user_name = request.session.get("user_name", "User")

        google_sheet_client_manager = GoogleSheetClientManager(creds_json=creds_json)
        service = AmiiboService(google_sheet_client_manager=google_sheet_client_manager)
        config = GoogleSheetConfigManager(
            google_sheet_client_manager=google_sheet_client_manager
        )
        dark_mode = config.is_dark_mode()

        amiibos = service.fetch_amiibos()
        available_types = sorted(
            {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
        )
        ignored_types = config.get_ignored_types(available_types)
        filtered_amiibos = [a for a in amiibos if a.get("type") not in ignored_types]

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
            },
        )


@method_decorator(csrf_exempt, name="dispatch")
class ToggleDarkModeView(View):
    def post(self, request):
        creds_json = request.session.get("credentials")
        if not creds_json:
            return redirect("oauth_login")

        google_sheet_client_manager = GoogleSheetClientManager(creds_json=creds_json)

        try:
            data = json.loads(request.body)
            enable_dark = data.get("dark_mode", True)

            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_dark_mode(enable_dark)

            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleTypeFilterView(View):
    def post(self, request):
        creds_json = request.session.get("credentials")
        if not creds_json:
            return redirect("oauth_login")

        google_sheet_client_manager = GoogleSheetClientManager(creds_json=creds_json)

        try:
            data = json.loads(request.body)
            amiibo_type = data.get("type")
            ignore = data.get("ignore", True)

            if not amiibo_type:
                return JsonResponse(
                    {"status": "error", "message": "Missing type"}, status=400
                )

            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_ignore_type(amiibo_type, ignore)

            return JsonResponse({"status": "success"})
        except Exception as e:
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
