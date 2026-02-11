"""
Sitemap definitions for SEO optimization.
"""

import json
from pathlib import Path
from datetime import datetime
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.core.cache import cache
import requests


class StaticViewSitemap(Sitemap):
    """Sitemap for static pages."""

    priority = 0.8
    changefreq = "monthly"

    def items(self):
        """Return list of static page URL names."""
        return ["index", "amiibodex", "blog_list", "demo", "about", "privacy"]

    def location(self, item):
        """Return the URL for each item."""
        return reverse(item)


class BlogPostSitemap(Sitemap):
    """Sitemap for blog posts."""

    priority = 0.9
    changefreq = "weekly"

    def items(self):
        """Return list of blog posts from JSON file."""
        blog_posts_path = Path(__file__).parent / "data" / "blog_posts.json"
        try:
            with blog_posts_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return data.get("posts", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading blog posts for sitemap: {e}")
            return []

    def location(self, item):
        """Return the URL for each blog post."""
        return reverse("blog_post", kwargs={"slug": item["slug"]})

    def lastmod(self, item):
        """Return last modification date (publication date for blog posts)."""
        try:
            return datetime.strptime(item["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            return None


class AmiiboSitemap(Sitemap):
    """Sitemap for individual amiibo detail pages."""

    priority = 0.7
    changefreq = "monthly"
    limit = 1000  # Limit items per sitemap file

    def items(self):
        """
        Fetch all amiibo from the API and return them.
        Uses caching to avoid excessive API calls.
        """
        cache_key = "amiibo_sitemap_data"
        cache_timeout = 86400  # 24 hours

        # Try to get cached data
        cached_amiibos = cache.get(cache_key)
        if cached_amiibos is not None:
            return cached_amiibos

        # Fetch from API
        try:
            response = requests.get("https://www.amiiboapi.com/api/amiibo/", timeout=10)
            response.raise_for_status()
            data = response.json()
            amiibos = data.get("amiibo", [])

            # Cache the results
            cache.set(cache_key, amiibos, cache_timeout)

            return amiibos
        except Exception as e:
            # Log error but return empty list to prevent sitemap generation failure
            print(f"Error fetching amiibo for sitemap: {e}")
            return []

    def location(self, item):
        """Return the URL for each amiibo detail page."""
        head = item.get("head", "")
        tail = item.get("tail", "")
        amiibo_id = f"{head}-{tail}"
        return reverse("amiibo_detail", kwargs={"amiibo_id": amiibo_id})

    def lastmod(self, item):
        """
        Return last modification date.
        Use earliest release date as lastmod.
        """
        release_dates = item.get("release", {})
        for region in ["na", "jp", "eu", "au"]:
            date_str = release_dates.get(region)
            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except (ValueError, TypeError):
                    pass
        return None
