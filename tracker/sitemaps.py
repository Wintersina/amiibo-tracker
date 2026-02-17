"""
Sitemap definitions for SEO optimization.
"""

import json
from pathlib import Path
from datetime import datetime
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.core.cache import cache


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
        Fetch all amiibo from the local database and return them.
        Uses caching to avoid excessive file reads.
        """
        cache_key = "amiibo_sitemap_data"
        cache_timeout = 86400  # 24 hours

        # Try to get cached data
        cached_amiibos = cache.get(cache_key)
        if cached_amiibos is not None:
            return cached_amiibos

        # Fetch from local database
        database_path = Path(__file__).parent / "data" / "amiibo_database.json"
        try:
            with database_path.open(encoding="utf-8") as database_file:
                data = json.load(database_file)
                amiibos = data.get("amiibo", [])

                # Filter out unreleased/upcoming amiibos
                # Note: NEVER filter 00000000 IDs - some released amiibos have them (like 8-Bit Mario)
                filtered_amiibos = []
                for amiibo in amiibos:
                    # Skip if explicitly marked as upcoming
                    if amiibo.get("is_upcoming", False):
                        continue

                    head = amiibo.get("head", "")
                    tail = amiibo.get("tail", "")
                    has_ff_placeholder = head.startswith("ff") or tail.startswith("ff")

                    if has_ff_placeholder:
                        # Check if it has any release dates
                        release_dates = amiibo.get("release", {})
                        has_release = any(
                            release_dates.get(region) for region in ["na", "jp", "eu", "au"]
                        )
                        # Only skip if ff placeholder AND no release dates
                        if not has_release:
                            continue

                    # Include this amiibo
                    filtered_amiibos.append(amiibo)

                # Cache the results
                cache.set(cache_key, filtered_amiibos, cache_timeout)

                return filtered_amiibos
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
