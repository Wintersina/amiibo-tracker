from urllib.parse import quote
from django import template

register = template.Library()


@register.filter(name="amiibo_image")
def amiibo_image(amiibo):
    """
    Returns a URL that will serve the image with background removed for upcoming amiibos only.

    Official AmiiboAPI images already have transparent backgrounds, so we only process
    newly scraped amiibos (is_upcoming=True) from Nintendo's website.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image }}" alt="{{ amiibo.name }}">
    """
    original_image = amiibo.get("image", "")
    if not original_image:
        return ""

    # Only process background removal for upcoming amiibos (newly scraped from Nintendo)
    # Official AmiiboAPI images already have transparent backgrounds
    if amiibo.get("is_upcoming"):
        # Return URL to our background removal API endpoint
        encoded_url = quote(original_image, safe="")
        return f"/api/remove-bg/?url={encoded_url}"

    # Return original image for official amiibos (already has transparent background)
    return original_image


@register.filter(name="amiibo_image_original")
def amiibo_image_original(amiibo):
    """
    Returns the original image URL without background removal.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image_original }}" alt="{{ amiibo.name }}">
    """
    return amiibo.get("image", "")
