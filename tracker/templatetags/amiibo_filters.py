from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="amiibo_image")
def amiibo_image(amiibo):
    """
    Returns the image URL for an amiibo.

    Both AmiiboAPI and amiibo.life images already have transparent backgrounds,
    so no background removal processing is needed.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image }}" alt="{{ amiibo.name }}">
    """
    original_image = amiibo.get("image", "")
    if not original_image:
        return ""

    # UPDATED: No background removal needed anymore
    # - AmiiboAPI images already have transparent backgrounds
    # - amiibo.life images (new source) also have transparent backgrounds
    # Return the URL directly (no encoding needed for img src attributes)
    return original_image


@register.filter(name="amiibo_image_original")
def amiibo_image_original(amiibo):
    """
    Returns the original image URL without background removal.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image_original }}" alt="{{ amiibo.name }}">
    """
    return amiibo.get("image", "")
