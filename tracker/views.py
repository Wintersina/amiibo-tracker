import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from tracker.service_domain import AmiiboService


@csrf_exempt
def toggle_collected(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amiibo_id = data['amiibo_id']
            action = data['action']

            service = AmiiboService()
            success = service.toggle_collected(amiibo_id, action)

            if not success:
                return JsonResponse({'status': 'not found'}, status=404)

            return JsonResponse({'status': 'success'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'invalid method'}, status=400)

def amiibo_list(request):
    service = AmiiboService()

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
    return render(request, "tracker/amiibos.html", {"amiibos": sorted_amiibos})