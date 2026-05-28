from datetime import datetime

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="iso_long_date")
def iso_long_date(value):
    """Render an ISO date string (YYYY-MM-DD) as 'Mon DD, YYYY'."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return value


@register.filter(name="iso_short_date")
def iso_short_date(value):
    """Render an ISO date string (YYYY-MM-DD) as 'Mon DD'."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d")
    except (TypeError, ValueError):
        return value


@register.filter(name="amiibo_image")
def amiibo_image(amiibo):
    """
    Returns the image URL for an amiibo.

    Prefers the WebP variant (imgwebp) for faster page loads, falling
    back to the PNG (image) when WebP isn't available.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image }}" alt="{{ amiibo.name }}">
    """
    return amiibo.get("imgwebp") or amiibo.get("image", "")


@register.filter(name="amiibo_image_original")
def amiibo_image_original(amiibo):
    """
    Returns the original image URL without background removal.

    Usage in templates:
        <img src="{{ amiibo|amiibo_image_original }}" alt="{{ amiibo.name }}">
    """
    return amiibo.get("image", "")
