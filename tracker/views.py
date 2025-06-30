import json
import os

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from tracker.service_domain import AmiiboService, GoogleSheetConfigManager


@csrf_exempt
def toggle_collected(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            amiibo_id = data["amiibo_id"]
            action = data["action"]

            service = AmiiboService()
            success = service.toggle_collected(amiibo_id, action)

            if not success:
                return JsonResponse({"status": "not found"}, status=404)

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "invalid method"}, status=400)


class MainView(View):

    CLIENT_SECRETS = os.path.join(settings.BASE_DIR, "client_secret.json")
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    REDIRECT_URI = "http://localhost:8000/oauth2callback/"

    def oauth_login(self, request):
        flow = Flow.from_client_secrets_file(
            self.CLIENT_SECRETS, scopes=self.SCOPES, redirect_uri=self.REDIRECT_URI
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true"
        )
        request.session["flow"] = flow.authorization_url  # store flow if needed
        return redirect(auth_url)

    def oauth2callback(self, request):
        flow = Flow.from_client_secrets_file(
            self.CLIENT_SECRETS, scopes=self.SCOPES, redirect_uri=self.REDIRECT_URI
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        creds = flow.credentials
        request.session["credentials"] = creds.to_json()
        return redirect("amiibo_list")

    def amiibo_list(self, request):
        creds_json = request.session.get("credentials")
        if not creds_json:
            return redirect("oauth_login")

        creds = Credentials.from_authorized_user_info(
            json.loads(creds_json), self.SCOPES
        )

        service = AmiiboService()
        config = GoogleSheetConfigManager()
        dark_mode = config.is_dark_mode()

        # Fetch all amiibos from external API
        amiibos = service.fetch_amiibos()

        # Filter out types we don't want to track
        ignore_types = ["Yarn", "Card", "Band"]
        amiibos = [a for a in amiibos if a["type"] not in ignore_types]

        # Ensure all new amiibos are seeded in the Sheet with default collected=0
        service.seed_new_amiibos(amiibos)

        # Get collected status from Sheet
        collected_status = service.get_collected_status()

        # Attach collected flag to each amiibo
        for amiibo in amiibos:
            amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
            amiibo["collected"] = collected_status.get(amiibo_id) == "1"

        # Sort for nicer UI grouping
        sorted_amiibos = sorted(amiibos, key=lambda x: (x["amiiboSeries"], x["name"]))

        # Render the template
        return render(
            request,
            "tracker/amiibos.html",
            {"amiibos": sorted_amiibos, "dark_mode": dark_mode},
        )


@csrf_exempt
def toggle_dark_mode(request):
    if request.method == "POST":

        try:
            data = json.loads(request.body)

            enable_dark = data.get("dark_mode", True)

            config = GoogleSheetConfigManager()
            config.set_dark_mode(enable_dark)

            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    return JsonResponse({"status": "invalid method"}, status=400)
