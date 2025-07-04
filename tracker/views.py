import json
from collections import defaultdict

import googleapiclient
from django.contrib.auth import logout as django_logout
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from googleapiclient.discovery import build

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager


@csrf_exempt
def toggle_collected(request):
    if request.method == "POST":
        creds_json = request.session.get("credentials")
        if not creds_json:
            return JsonResponse(
                {"status": "unauthenticated", "redirect_url": reverse("oauth_login")},
                status=401,
            )  # Return JSON for AJAX, then redirect on client-side

        # No change needed here, as it still uses creds_json from session
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
    # Instantiate the manager to get the flow, which will fetch secrets
    manager = GoogleSheetClientManager()  # No need for creds_json here
    flow = manager.get_flow()  # Use the new method to get the Flow instance

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    request.session["oauth_state"] = state  # Store 'oauth_state'
    return redirect(auth_url)


def oauth2callback(request):
    def credentials_to_dict(creds):
        creds_dict = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,  # This can be sensitive; ensure it's handled securely
            "scopes": creds.scopes,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,  # Add expiry
        }

        if hasattr(creds, "client_secret") and creds.client_secret:
            creds_dict["client_secret"] = creds.client_secret
        return creds_dict

    # Instantiate the manager to get the flow
    manager = GoogleSheetClientManager()  # No need for creds_json here
    flow = manager.get_flow()  # Use the new method to get the Flow instance

    state = request.session.pop("oauth_state", None)  # Retrieve 'oauth_state'
    if state != request.GET.get("state"):
        # For security, strictly check the state parameter
        print(
            f"State mismatch: Session '{state}', Request '{request.GET.get('state')}'"
        )
        return HttpResponseBadRequest("Invalid state parameter")

    try:
        # Pass the original scopes from OauthConstants used for the flow
        # This ensures the token fetching uses the correct scope set.
        flow.fetch_token(
            authorization_response=request.build_absolute_uri(),
            scopes=OauthConstants.SCOPES,
        )
    except Exception as e:
        print(f"Error fetching token: {e}")
        return HttpResponseBadRequest(f"Error fetching token: {e}")

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
    django_logout(request)
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

    amiibos = service.fetch_amiibos()

    ignore_types = ["Yarn", "Card", "Band"]
    amiibos = [a for a in amiibos if a["type"] not in ignore_types]

    service.seed_new_amiibos(amiibos)

    collected_status = service.get_collected_status()

    for amiibo in amiibos:
        amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
        amiibo["collected"] = collected_status.get(amiibo_id) == "1"

    sorted_amiibos = sorted(amiibos, key=lambda x: (x["amiiboSeries"], x["name"]))

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
    print(enriched_groups)
    return render(
        request,
        "tracker/amiibos.html",
        {
            "amiibos": sorted_amiibos,
            "dark_mode": dark_mode,
            "user_name": user_name,
            "grouped_amiibos": enriched_groups,
        },
    )


@csrf_exempt
def toggle_dark_mode(request):
    if request.method == "POST":
        creds_json = request.session.get("credentials")
        if not creds_json:
            return JsonResponse(
                {"status": "unauthenticated", "redirect_url": reverse("oauth_login")},
                status=401,
            )

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
