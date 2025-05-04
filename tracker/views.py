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

    rows = sheet.get_all_values()[1:]  # Skip header row

    collected_status = {row[0]: row[2] for row in rows}  # {ID: '1' or '0'}
    ignore_types = ["Yarn", "Card", "Band"]
    amiibos = [amiibo for amiibo in amiibos if amiibo["type"] not in ignore_types]
    seed_new_amiibo(amiibos)
    for amiibo in amiibos:
        amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
        amiibo["collected"] = collected_status.get(amiibo_id) == "1"

    sorted_amiibos = sorted(amiibos, key=lambda x: (x["amiiboSeries"], x["name"]))

    return render(request, "tracker/amiibos.html", {"amiibos": sorted_amiibos})


def seed_new_amiibo(amiibos: list[dict]):
    sheet = get_sheet()

    existing_ids = sheet.col_values(1)[1:]

    new_rows = []

    for amiibo in amiibos:
        amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]

        if amiibo_id not in existing_ids:
            new_rows.append([amiibo_id, amiibo["name"], "0"])

    if new_rows:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")


@csrf_exempt
def toggle_collected(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        amiibo_id = data['amiibo_id']
        action = data['action']

        sheet = get_sheet()
        current_ids = sheet.col_values(1)[1:]

        try:
            if action == 'collect' and amiibo_id in current_ids:
                print(f"do: {amiibo_id}")
                cell = sheet.find(amiibo_id)
                sheet.update_cell(cell.row, 3, "1")

            elif action == 'uncollect' and amiibo_id in current_ids:
                print(f"undo: {amiibo_id}")
                cell = sheet.find(amiibo_id)
                sheet.update_cell(cell.row, 3, "0")

            return JsonResponse({'status': 'success'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'invalid'}, status=400)
