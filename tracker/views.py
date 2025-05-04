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
    seed_new_amiibo(amiibos)
    for amiibo in amiibos:
        amiibo_id = amiibo["head"] + amiibo["tail"]
        amiibo["collected"] = collected_status.get(amiibo_id) == "1"

    sorted_amiibos = sorted(amiibos, key=lambda x: (x["amiiboSeries"], x["name"]))

    return render(request, "tracker/amiibos.html", {"amiibos": sorted_amiibos})

def seed_new_amiibo(amiibos: list[dict]):
    # Get the sheet object using `get_sheet`
    sheet = get_sheet()

    # Fetch all current Amiibo IDs in the sheet (Column A, excluding the header)
    existing_ids = sheet.col_values(1)[1:]  # Skip header row

    # Prepare rows to append for non-existing Amiibos
    new_rows = []

    for amiibo in amiibos:
        # Construct the unique ID using `head` + `tail`
        amiibo_id = amiibo["head"] + amiibo["tail"]

        # If this ID is not already in the sheet, prepare its data
        if amiibo_id not in existing_ids:
            # Add new row with ID, Name, and Collected status (default: 0)
            new_rows.append([amiibo_id, amiibo["name"], "0"])

    # Append all new rows to the sheet at once (if any)
    if new_rows:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")

@csrf_exempt
def toggle_collected(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        amiibo_id = data['amiibo_id']
        action = data['action']

        sheet = get_sheet()  # Access the sheet
        current_ids = sheet.col_values(1)[1:]  # Get all current Amiibo IDs (skip header row)

        try:
            if action == 'collect':
                # Check if amiibo_id exists in the sheet
                if amiibo_id in current_ids:
                    # Find the row of the existing amiibo_id
                    cell = sheet.find(amiibo_id)
                    # Update the corresponding Collected Status column (Column C) to "1"
                    sheet.update_cell(cell.row, 3, "1")
                else:
                    # If not present, append a new row with Collected Status = 1
                    sheet.append_row([amiibo_id, "", "1"], value_input_option="USER_ENTERED")

            elif action == 'uncollect':
                # Check if amiibo_id exists in the sheet
                if amiibo_id in current_ids:
                    # Find the row of the existing amiibo_id
                    cell = sheet.find(amiibo_id)
                    # Update the corresponding Collected Status column (Column C) to "0"
                    sheet.update_cell(cell.row, 3, "0")

            return JsonResponse({'status': 'success'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'invalid'}, status=400)
