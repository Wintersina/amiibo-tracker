import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager


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
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    request.session["oauth_state"] = _

    return redirect(auth_url)


def oauth2callback(request):
    state = request.session.get("oauth_state")
    flow = Flow.from_client_secrets_file(
        GoogleSheetClientManager.CLIENT_SECRETS,
        scopes=OauthConstants.SCOPES,
        redirect_uri=OauthConstants.REDIRECT_URI,
        state=state,  # restore the state
    )
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    creds = flow.credentials
    print("Access Token:", creds.token)
    print("Refresh Token:", creds.refresh_token)
    request.session["credentials"] = creds.to_json()
    return redirect("amiibo_list")


def amiibo_list(request):
    creds_json = request.session.get("credentials")
    if not creds_json:
        return redirect("oauth_login")

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
        {"amiibos": sorted_amiibos, "dark_mode": dark_mode},
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
