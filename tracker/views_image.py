import hashlib
from io import BytesIO
from urllib.parse import urlparse

import numpy as np
import requests as http_requests
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from PIL import Image
from rembg import remove, new_session
from scipy.ndimage import binary_erosion

from tracker.helpers import LoggingMixin

# Allowed domains for security - only process images from trusted sources
ALLOWED_DOMAINS = {
    "www.nintendo.com",
    "assets.nintendo.com",
    "raw.githubusercontent.com",
    "amiiboapi.org",
}

# Pre-load rembg session for better performance
# This loads the ML model once instead of on every request
# u2net_human_seg is optimized for figures/characters (perfect for amiibos!)
try:
    print("Loading rembg model: u2net_human_seg...")
    _session = new_session("u2net_human_seg")
    print("Rembg model loaded successfully")
except Exception as e:
    print(f"Warning: Failed to pre-load rembg model: {e}")
    print("Model will be loaded on first request")
    _session = None


def remove_white_fringe(img, threshold=240):
    """
    Remove white/near-white pixels near transparent edges.

    This fixes the common "white halo" artifact that appears after background removal,
    where white pixels from the original background remain around the edges.

    Args:
        img: PIL Image in RGBA format
        threshold: RGB threshold for what counts as "white" (0-255, default 240)

    Returns:
        PIL Image with white fringe removed
    """
    data = np.array(img.convert("RGBA"))

    # Find semi-transparent or near-edge pixels
    alpha = data[:, :, 3]
    rgb = data[:, :, :3]

    # Where pixels are mostly white AND near a transparent edge
    is_white = np.all(rgb > threshold, axis=2)
    is_visible = alpha > 0

    # Erode alpha slightly to find edge region
    interior = binary_erosion(alpha > 128, iterations=3)
    edge_region = is_visible & ~interior

    # Kill white pixels in the edge region
    kill = is_white & edge_region
    data[kill, 3] = 0

    return Image.fromarray(data)


class ImageProcessingMixin(LoggingMixin):
    """Mixin for image processing views"""

    pass


def remove_bg(request):
    """
    DISABLED: Background removal endpoint (no longer needed with amiibo.life images).

    Previously used to remove backgrounds from Nintendo.com images.
    Now disabled to reduce memory requirements in Cloud Run.

    Usage: /api/remove-bg/?url=<image_url>

    Returns: Error message indicating endpoint is disabled
    """
    return HttpResponseBadRequest(
        "Background removal endpoint is disabled. "
        "amiibo.life images already have transparent backgrounds."
    )

# DEPRECATED CODE - kept for reference
# def remove_bg_original(request):
#     """
#     API endpoint to remove background from an image URL.
#
#     Usage: /api/remove-bg/?url=<image_url>
#
#     Returns: PNG image with transparent background
#     Caches: Results cached for 1 hour (3600 seconds)
#     """
#     url = request.GET.get("url")
#     if not url:
#         return HttpResponseBadRequest("Missing 'url' query parameter.")
#
#     # Restrict to allowed domains for security
#     domain = urlparse(url).hostname
#     if ALLOWED_DOMAINS and domain not in ALLOWED_DOMAINS:
#         return HttpResponseBadRequest(f"Domain '{domain}' is not allowed.")
#
#     # Check cache first
#     cache_key = f"rembg_{hashlib.md5(url.encode()).hexdigest()}"
#     cached = cache.get(cache_key)
#     if cached:
#         return HttpResponse(cached, content_type="image/png")
#
#     # Fetch the image
#     try:
#         resp = http_requests.get(url, timeout=10)
#         resp.raise_for_status()
#     except http_requests.RequestException as e:
#         return HttpResponseBadRequest(f"Failed to fetch image: {e}")
#
#     # Remove background
#     try:
#         input_img = Image.open(BytesIO(resp.content))
#         # Lazy-load session if it wasn't pre-loaded
#         session = _session if _session is not None else new_session("u2net_human_seg")
#         output_img = remove(input_img, session=session)
#
#         # Remove white fringe artifacts around edges
#         output_img = remove_white_fringe(output_img)
#     except Exception as e:
#         return HttpResponseBadRequest(f"Failed to process image: {e}")
#
#     # Write to buffer
#     buf = BytesIO()
#     output_img.save(buf, format="PNG")
#     png_bytes = buf.getvalue()
#
#     # Cache for 1 hour (3600 seconds)
#     cache.set(cache_key, png_bytes, timeout=3600)
#
#     return HttpResponse(png_bytes, content_type="image/png")
