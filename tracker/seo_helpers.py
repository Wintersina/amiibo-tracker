"""
SEO helper utilities for generating meta tags, structured data, and SEO context.
"""

import json
import re
from html import escape
from datetime import datetime
from urllib.parse import urljoin


class SEOContext:
    """Builder pattern for constructing SEO metadata."""

    def __init__(self, request=None):
        self.request = request
        self.data = {
            "title": "Amiibo Tracker",
            "meta_description": "Track your Amiibo collection",
            "og_type": "website",
            "og_image": None,
            "og_url": None,
            "canonical_url": None,
            "schemas": [],
        }

    def set_title(self, title, suffix="Amiibo Tracker"):
        """Set page title with optional suffix. Truncates to 60 characters."""
        if suffix:
            full_title = f"{title} - {suffix}"
        else:
            full_title = title

        # Truncate to 60 characters for SEO best practices
        if len(full_title) > 60:
            full_title = full_title[:57] + "..."

        self.data["title"] = full_title
        return self

    def set_description(self, description):
        """Set meta description. Truncates to 155 characters."""
        # Strip HTML tags if present
        description = re.sub(r"<[^>]+>", "", description)

        # Truncate to 155 characters for SEO best practices
        if len(description) > 155:
            # Try to break at a sentence or word boundary
            description = description[:152] + "..."

        self.data["meta_description"] = description
        return self

    def set_type(self, og_type):
        """Set OpenGraph type (website, article, product, etc.)."""
        self.data["og_type"] = og_type
        return self

    def set_og_image(self, image_url):
        """Set OpenGraph image URL."""
        if self.request and not image_url.startswith("http"):
            # Convert relative URL to absolute
            image_url = self.request.build_absolute_uri(image_url)
        self.data["og_image"] = image_url
        return self

    def set_canonical_url(self, url):
        """Set canonical URL."""
        if self.request and not url.startswith("http"):
            # Convert relative URL to absolute
            url = self.request.build_absolute_uri(url)
        self.data["canonical_url"] = url
        return self

    def add_schema(self, schema_type, schema_data):
        """Add JSON-LD structured data schema."""
        schema_data["@context"] = "https://schema.org"
        schema_data["@type"] = schema_type
        self.data["schemas"].append(schema_data)
        return self

    def build(self):
        """Build and return the final SEO context dictionary."""
        # Auto-generate canonical URL if not set
        if not self.data["canonical_url"] and self.request:
            self.data["canonical_url"] = self.request.build_absolute_uri()

        # Auto-generate OG URL if not set
        if not self.data["og_url"] and self.request:
            self.data["og_url"] = self.request.build_absolute_uri()

        # Serialize schemas to JSON strings
        self.data["schemas_json"] = [
            json.dumps(schema, ensure_ascii=False) for schema in self.data["schemas"]
        ]

        return self.data


def generate_meta_description(content, max_length=155):
    """
    Generate a meta description from HTML content.
    Strips HTML tags, extracts first sentences, and limits to max_length.
    """
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", content)

    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # If already short enough, return it
    if len(text) <= max_length:
        return text

    # Try to break at sentence boundary (period followed by space)
    truncated = text[:max_length]
    last_period = truncated.rfind(". ")

    if last_period > max_length * 0.6:  # If we found a period in the last 40%
        return text[: last_period + 1]

    # Otherwise, break at word boundary
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return text[:last_space] + "..."

    # Last resort: hard truncate
    return text[: max_length - 3] + "..."


def generate_article_schema(
    title,
    description,
    url,
    date_published,
    author="Amiibo Tracker",
    publisher="Amiibo Tracker",
    image=None,
):
    """
    Generate Article schema (JSON-LD) for blog posts.

    Args:
        title: Article title
        description: Article description/excerpt
        url: Full URL to the article
        date_published: Publication date (string in ISO format or datetime object)
        author: Author name (default: 'Amiibo Tracker')
        publisher: Publisher name (default: 'Amiibo Tracker')
        image: URL to article image (optional)

    Returns:
        Dictionary representing Article schema
    """
    # Convert datetime to ISO string if needed
    if isinstance(date_published, datetime):
        date_published = date_published.isoformat()

    schema = {
        "headline": title,
        "description": description,
        "url": url,
        "datePublished": date_published,
        "dateModified": date_published,
        "author": {"@type": "Person", "name": author},
        "publisher": {
            "@type": "Organization",
            "name": publisher,
            "logo": {
                "@type": "ImageObject",
                "url": "https://amiibotracker.app/static/favicon.ico",
            },
        },
    }

    if image:
        schema["image"] = image

    return schema


def generate_blog_posting_schema(
    name,
    description,
    image,
    url,
    date_published=None,
    author="Amiibo Tracker",
    publisher="Amiibo Tracker",
):
    """
    Generate BlogPosting schema (JSON-LD) for amiibo detail pages.

    Since amiibo pages are wiki-style informational entries, BlogPosting is more
    appropriate than Product schema, avoiding Google's requirement for offers/reviews.

    Args:
        name: Article/posting name (amiibo name)
        description: Article description
        image: URL to article image
        url: Full URL to the article page
        date_published: Publication/release date (optional, string in ISO format or datetime object)
        author: Author name (default: 'Amiibo Tracker')
        publisher: Publisher name (default: 'Amiibo Tracker')

    Returns:
        Dictionary representing BlogPosting schema
    """
    # Convert datetime to ISO string if needed
    if isinstance(date_published, datetime):
        date_published = date_published.isoformat()

    schema = {
        "headline": name,
        "name": name,
        "description": description,
        "image": image,
        "url": url,
        "author": {"@type": "Person", "name": author},
        "publisher": {
            "@type": "Organization",
            "name": publisher,
            "logo": {
                "@type": "ImageObject",
                "url": "https://goozamiibo.com/static/favicon.ico",
            },
        },
    }

    if date_published:
        schema["datePublished"] = date_published
        schema["dateModified"] = date_published

    return schema


def generate_breadcrumb_schema(items):
    """
    Generate BreadcrumbList schema (JSON-LD).

    Args:
        items: List of tuples (name, url) representing breadcrumb trail
               Example: [('Home', '/'), ('Blog', '/blog/'), ('Post', '/blog/post/')]

    Returns:
        Dictionary representing BreadcrumbList schema
    """
    list_items = []
    for position, (name, url) in enumerate(items, start=1):
        list_items.append(
            {"@type": "ListItem", "position": position, "name": name, "item": url}
        )

    return {"itemListElement": list_items}


def generate_organization_schema(
    name="Amiibo Tracker",
    url="https://amiibotracker.app",
    logo="https://amiibotracker.app/static/favicon.ico",
):
    """
    Generate Organization schema (JSON-LD) for the site.

    Args:
        name: Organization name
        url: Organization website URL
        logo: URL to organization logo

    Returns:
        Dictionary representing Organization schema
    """
    return {"name": name, "url": url, "logo": logo}


def generate_website_schema(
    name="Amiibo Tracker",
    url="https://amiibotracker.app",
    search_url="https://amiibotracker.app/amiibos/?search={search_term_string}",
):
    """
    Generate WebSite schema (JSON-LD) with SearchAction.

    Args:
        name: Website name
        url: Website URL
        search_url: Search URL template with {search_term_string} placeholder

    Returns:
        Dictionary representing WebSite schema
    """
    return {
        "name": name,
        "url": url,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": search_url},
            "query-input": "required name=search_term_string",
        },
    }
