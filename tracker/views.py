import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("AmiiboCollection").sheet1
    return sheet

def fetch_amiibos():
    response = requests.get("https://amiiboapi.com/api/amiibo/")
    return response.json().get("amiibo", [])

def amiibo_list(request):
    amiibos = fetch_amiibos()
    sheet = get_sheet()

    # Get all rows except the header
    rows = sheet.get_all_values()[1:]  # Skip header row

    # Create a dictionary for collected data: {amiibo_id: collected_status}
    collected_status = {row[0]: row[2] for row in rows}  # {ID: '1' or '0'}

    # Filter out 'Card' Amiibos and add collection status to them
    amiibos = [amiibo for amiibo in amiibos if amiibo["type"] != "Card" and amiibo["type"] != "Band"]

    for amiibo in amiibos:
        amiibo_id = amiibo["head"] + amiibo["tail"]
        amiibo["collected"] = collected_status.get(amiibo_id) == "1"

    return render(request, "tracker/amiibos.html", {"amiibos": amiibos})

@csrf_exempt
def toggle_collected(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        amiibo_id = data['amiibo_id']
        action = data['action']

        sheet = get_sheet()
        current_ids = sheet.col_values(1)[1:]

        if action == 'collect' and amiibo_id not in current_ids:
            sheet.append_row([amiibo_id])
        elif action == 'uncollect':
            try:
                cell = sheet.find(amiibo_id)
                sheet.delete_row(cell.row)
            except:
                pass

        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'invalid'}, status=400)
