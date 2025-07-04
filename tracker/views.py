import json

import googleapiclient
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager
from django.contrib.auth import logout as django_logout
import requests
from googleapiclient.discovery import build


@csrf_exempt
def toggle_collected(request):
    if request.method == "POST":
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

    return JsonResponse({"status": "invalid method"}, status=400)


def oauth_login(request):
    flow = Flow.from_client_secrets_file(
        GoogleSheetClientManager.CLIENT_SECRETS,
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


def oauth2callback(request):
    def credentials_to_dict(creds):
        return {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }

    flow = Flow.from_client_secrets_file(
        "client_secret.json",
        scopes=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
        redirect_uri=request.build_absolute_uri(reverse("oauth2callback")),
    )

    state = request.session.pop("state", None)
    # if state != request.GET.get('state'):
    #     return HttpResponseBadRequest("Invalid state parameter")
    print(state)
    flow.fetch_token(authorization_response=request.build_absolute_uri())

    credentials = flow.credentials

    request.session["credentials"] = credentials_to_dict(credentials)

    user_service = googleapiclient.discovery.build(
        "oauth2", "v2", credentials=credentials
    )
    user_info = user_service.userinfo().get().execute()

    # Store in session
    request.session["user_name"] = user_info.get("name")
    request.session["user_email"] = user_info.get("email")

    return redirect("amiibo_list")


def logout_view(request):
    request.session.flush()
    django_logout(request)  # Optional: Django logout if using auth system
    return redirect("index")


def amiibo_list(request):
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
        {"amiibos": sorted_amiibos, "dark_mode": dark_mode, "user_name": user_name},
    )


@csrf_exempt
def toggle_dark_mode(request):

    if request.method == "POST":
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
    return JsonResponse({"status": "invalid method"}, status=400)


def index(request):
    if request.user.is_authenticated:
        return redirect("amiibo_list")
    return render(request, "tracker/index.html")
