"""
Comprehensive pytest tests for SEO helper functions and classes.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock
from tracker.seo_helpers import (
    SEOContext,
    generate_meta_description,
    generate_article_schema,
    generate_blog_posting_schema,
    generate_breadcrumb_schema,
    generate_organization_schema,
    generate_website_schema,
)


class TestSEOContext:
    """Tests for the SEOContext builder class."""

    def test_initialization_with_request(self):
        """Test SEOContext initialization with a request object."""
        request = Mock()
        request.build_absolute_uri = Mock(return_value="https://example.com/page/")

        seo = SEOContext(request)

        assert seo.request == request
        assert seo.data["title"] == "Amiibo Tracker"
        assert seo.data["meta_description"] == "Track your Amiibo collection"
        assert seo.data["og_type"] == "website"

    def test_initialization_without_request(self):
        """Test SEOContext initialization without a request object."""
        seo = SEOContext()

        assert seo.request is None
        assert seo.data["title"] == "Amiibo Tracker"

    def test_set_title_with_suffix(self):
        """Test setting title with default suffix."""
        seo = SEOContext()
        seo.set_title("Blog Post")

        assert seo.data["title"] == "Blog Post - Amiibo Tracker"

    def test_set_title_without_suffix(self):
        """Test setting title without suffix."""
        seo = SEOContext()
        seo.set_title("Welcome", suffix="")

        assert seo.data["title"] == "Welcome"

    def test_set_title_truncation(self):
        """Test that title is truncated to 60 characters."""
        seo = SEOContext()
        long_title = "A" * 100
        seo.set_title(long_title, suffix="")

        assert len(seo.data["title"]) == 60
        assert seo.data["title"].endswith("...")

    def test_set_description(self):
        """Test setting meta description."""
        seo = SEOContext()
        description = "This is a test description for SEO."
        seo.set_description(description)

        assert seo.data["meta_description"] == description

    def test_set_description_truncation(self):
        """Test that description is truncated to 155 characters."""
        seo = SEOContext()
        long_description = "A" * 200
        seo.set_description(long_description)

        assert len(seo.data["meta_description"]) <= 155
        assert seo.data["meta_description"].endswith("...")

    def test_set_description_strips_html(self):
        """Test that HTML tags are stripped from description."""
        seo = SEOContext()
        html_description = "<p>This is <strong>bold</strong> text.</p>"
        seo.set_description(html_description)

        assert "<" not in seo.data["meta_description"]
        assert ">" not in seo.data["meta_description"]
        assert "This is bold text." in seo.data["meta_description"]

    def test_set_type(self):
        """Test setting OpenGraph type."""
        seo = SEOContext()
        seo.set_type("article")

        assert seo.data["og_type"] == "article"

    def test_set_og_image_relative_url(self):
        """Test setting OG image with relative URL."""
        request = Mock()
        request.build_absolute_uri = Mock(return_value="https://example.com/image.jpg")

        seo = SEOContext(request)
        seo.set_og_image("/static/image.jpg")

        assert seo.data["og_image"] == "https://example.com/image.jpg"

    def test_set_og_image_absolute_url(self):
        """Test setting OG image with absolute URL."""
        seo = SEOContext()
        seo.set_og_image("https://example.com/image.jpg")

        assert seo.data["og_image"] == "https://example.com/image.jpg"

    def test_set_canonical_url(self):
        """Test setting canonical URL."""
        request = Mock()
        request.build_absolute_uri = Mock(return_value="https://example.com/page/")

        seo = SEOContext(request)
        seo.set_canonical_url("/page/")

        assert seo.data["canonical_url"] == "https://example.com/page/"

    def test_add_schema(self):
        """Test adding JSON-LD schema."""
        seo = SEOContext()
        schema_data = {"name": "Test", "description": "Test schema"}
        seo.add_schema("Article", schema_data)

        assert len(seo.data["schemas"]) == 1
        assert seo.data["schemas"][0]["@context"] == "https://schema.org"
        assert seo.data["schemas"][0]["@type"] == "Article"
        assert seo.data["schemas"][0]["name"] == "Test"

    def test_build_auto_generates_urls(self):
        """Test that build() auto-generates canonical and OG URLs."""
        request = Mock()
        request.build_absolute_uri = Mock(return_value="https://example.com/page/")

        seo = SEOContext(request)
        result = seo.build()

        assert result["canonical_url"] == "https://example.com/page/"
        assert result["og_url"] == "https://example.com/page/"

    def test_build_serializes_schemas_to_json(self):
        """Test that build() serializes schemas to JSON strings."""
        seo = SEOContext()
        seo.add_schema("Organization", {"name": "Test Org"})
        result = seo.build()

        assert "schemas_json" in result
        assert len(result["schemas_json"]) == 1
        assert isinstance(result["schemas_json"][0], str)

        # Verify it's valid JSON
        parsed = json.loads(result["schemas_json"][0])
        assert parsed["@type"] == "Organization"
        assert parsed["name"] == "Test Org"

    def test_builder_pattern_chaining(self):
        """Test that methods can be chained."""
        seo = SEOContext()
        result = (
            seo.set_title("Test").set_description("Description").set_type("article")
        )

        assert isinstance(result, SEOContext)
        assert seo.data["title"] == "Test - Amiibo Tracker"
        assert seo.data["meta_description"] == "Description"
        assert seo.data["og_type"] == "article"


class TestGenerateMetaDescription:
    """Tests for the generate_meta_description function."""

    def test_short_content(self):
        """Test with content shorter than max_length."""
        content = "This is a short description."
        result = generate_meta_description(content)

        assert result == content

    def test_long_content_sentence_break(self):
        """Test that long content breaks at sentence boundary."""
        content = "First sentence. Second sentence. " + ("A" * 200)
        result = generate_meta_description(content, max_length=50)

        assert len(result) <= 50
        assert result.endswith(".")

    def test_long_content_word_break(self):
        """Test that long content breaks at word boundary if no sentence found."""
        content = "A" * 200
        result = generate_meta_description(content, max_length=50)

        assert len(result) <= 50
        assert result.endswith("...")

    def test_strips_html_tags(self):
        """Test that HTML tags are removed."""
        content = "<p>This is <strong>HTML</strong> content.</p>"
        result = generate_meta_description(content)

        assert "<" not in result
        assert ">" not in result
        assert "This is HTML content." in result

    def test_removes_extra_whitespace(self):
        """Test that extra whitespace is normalized."""
        content = "This  has   multiple    spaces."
        result = generate_meta_description(content)

        assert "  " not in result
        assert result == "This has multiple spaces."


class TestGenerateArticleSchema:
    """Tests for the generate_article_schema function."""

    def test_basic_article_schema(self):
        """Test generating basic article schema."""
        schema = generate_article_schema(
            title="Test Article",
            description="Test description",
            url="https://example.com/article/",
            date_published="2026-02-10",
        )

        assert schema["headline"] == "Test Article"
        assert schema["description"] == "Test description"
        assert schema["url"] == "https://example.com/article/"
        assert schema["datePublished"] == "2026-02-10"
        assert schema["dateModified"] == "2026-02-10"
        assert schema["author"]["@type"] == "Person"
        assert schema["author"]["name"] == "Amiibo Tracker"
        assert schema["publisher"]["@type"] == "Organization"

    def test_article_schema_with_datetime(self):
        """Test that datetime objects are converted to ISO format."""
        date = datetime(2026, 2, 10, 12, 30, 45)
        schema = generate_article_schema(
            title="Test",
            description="Test",
            url="https://example.com/",
            date_published=date,
        )

        assert schema["datePublished"] == "2026-02-10T12:30:45"

    def test_article_schema_with_image(self):
        """Test article schema with image."""
        schema = generate_article_schema(
            title="Test",
            description="Test",
            url="https://example.com/",
            date_published="2026-02-10",
            image="https://example.com/image.jpg",
        )

        assert schema["image"] == "https://example.com/image.jpg"

    def test_article_schema_custom_author(self):
        """Test article schema with custom author."""
        schema = generate_article_schema(
            title="Test",
            description="Test",
            url="https://example.com/",
            date_published="2026-02-10",
            author="Custom Author",
            publisher="Custom Publisher",
        )

        assert schema["author"]["name"] == "Custom Author"
        assert schema["publisher"]["name"] == "Custom Publisher"


class TestGenerateBlogPostingSchema:
    """Tests for the generate_blog_posting_schema function."""

    def test_basic_blog_posting_schema(self):
        """Test generating basic blog posting schema."""
        schema = generate_blog_posting_schema(
            name="Mario Amiibo",
            description="Mario figure from Super Mario series",
            image="https://example.com/mario.jpg",
            url="https://example.com/amiibo/mario/",
        )

        assert schema["name"] == "Mario Amiibo"
        assert schema["headline"] == "Mario Amiibo"
        assert schema["description"] == "Mario figure from Super Mario series"
        assert schema["image"] == "https://example.com/mario.jpg"
        assert schema["url"] == "https://example.com/amiibo/mario/"
        assert schema["author"]["@type"] == "Person"
        assert schema["author"]["name"] == "Amiibo Tracker"
        assert schema["publisher"]["@type"] == "Organization"
        assert schema["publisher"]["name"] == "Amiibo Tracker"

    def test_blog_posting_schema_with_date_published(self):
        """Test blog posting schema with publication date."""
        schema = generate_blog_posting_schema(
            name="Test",
            description="Test",
            image="",
            url="",
            date_published="2014-11-21",
        )

        assert schema["datePublished"] == "2014-11-21"
        assert schema["dateModified"] == "2014-11-21"

    def test_blog_posting_schema_custom_author(self):
        """Test blog posting schema with custom author and publisher."""
        schema = generate_blog_posting_schema(
            name="Test",
            description="Test",
            image="",
            url="",
            author="Custom Author",
            publisher="Custom Publisher",
        )

        assert schema["author"]["name"] == "Custom Author"
        assert schema["publisher"]["name"] == "Custom Publisher"

    def test_blog_posting_schema_with_datetime(self):
        """Test that datetime objects are converted to ISO format."""
        date = datetime(2014, 11, 21, 10, 30, 0)
        schema = generate_blog_posting_schema(
            name="Test",
            description="Test",
            image="",
            url="",
            date_published=date,
        )

        assert schema["datePublished"] == "2014-11-21T10:30:00"
        assert schema["dateModified"] == "2014-11-21T10:30:00"


class TestGenerateBreadcrumbSchema:
    """Tests for the generate_breadcrumb_schema function."""

    def test_basic_breadcrumb(self):
        """Test generating basic breadcrumb schema."""
        items = [
            ("Home", "https://example.com/"),
            ("Blog", "https://example.com/blog/"),
            ("Post", "https://example.com/blog/post/"),
        ]
        schema = generate_breadcrumb_schema(items)

        assert "itemListElement" in schema
        assert len(schema["itemListElement"]) == 3

        assert schema["itemListElement"][0]["@type"] == "ListItem"
        assert schema["itemListElement"][0]["position"] == 1
        assert schema["itemListElement"][0]["name"] == "Home"
        assert schema["itemListElement"][0]["item"] == "https://example.com/"

        assert schema["itemListElement"][2]["position"] == 3
        assert schema["itemListElement"][2]["name"] == "Post"

    def test_empty_breadcrumb(self):
        """Test breadcrumb with empty list."""
        schema = generate_breadcrumb_schema([])

        assert schema["itemListElement"] == []


class TestGenerateOrganizationSchema:
    """Tests for the generate_organization_schema function."""

    def test_default_organization_schema(self):
        """Test generating organization schema with defaults."""
        schema = generate_organization_schema()

        assert schema["name"] == "Amiibo Tracker"
        assert schema["url"] == "https://amiibotracker.app"
        assert schema["logo"] == "https://amiibotracker.app/static/favicon.ico"

    def test_custom_organization_schema(self):
        """Test generating organization schema with custom values."""
        schema = generate_organization_schema(
            name="Custom Org",
            url="https://custom.com",
            logo="https://custom.com/logo.png",
        )

        assert schema["name"] == "Custom Org"
        assert schema["url"] == "https://custom.com"
        assert schema["logo"] == "https://custom.com/logo.png"


class TestGenerateWebsiteSchema:
    """Tests for the generate_website_schema function."""

    def test_default_website_schema(self):
        """Test generating website schema with defaults."""
        schema = generate_website_schema()

        assert schema["name"] == "Amiibo Tracker"
        assert schema["url"] == "https://amiibotracker.app"
        assert schema["potentialAction"]["@type"] == "SearchAction"
        assert "urlTemplate" in schema["potentialAction"]["target"]
        assert (
            "{search_term_string}" in schema["potentialAction"]["target"]["urlTemplate"]
        )

    def test_custom_website_schema(self):
        """Test generating website schema with custom values."""
        schema = generate_website_schema(
            name="Custom Site",
            url="https://custom.com",
            search_url="https://custom.com/search?q={search_term_string}",
        )

        assert schema["name"] == "Custom Site"
        assert schema["url"] == "https://custom.com"
        assert (
            "https://custom.com/search?q="
            in schema["potentialAction"]["target"]["urlTemplate"]
        )


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_seo_context_build(self):
        """Test building a complete SEO context with all features."""
        request = Mock()
        request.build_absolute_uri = Mock(
            side_effect=lambda path="": f"https://example.com{path}"
        )

        seo = SEOContext(request)
        seo.set_title("Test Article", suffix="Test Site")
        seo.set_description("This is a test article about Amiibo collecting.")
        seo.set_type("article")
        seo.set_og_image("/static/image.jpg")

        # Add article schema
        article_schema = generate_article_schema(
            title="Test Article",
            description="Test description",
            url="https://example.com/article/",
            date_published="2026-02-10",
        )
        seo.add_schema("Article", article_schema)

        # Add breadcrumb schema
        breadcrumb_schema = generate_breadcrumb_schema(
            [
                ("Home", "https://example.com/"),
                ("Article", "https://example.com/article/"),
            ]
        )
        seo.add_schema("BreadcrumbList", breadcrumb_schema)

        result = seo.build()

        # Verify all context was built correctly
        assert result["title"] == "Test Article - Test Site"
        assert (
            result["meta_description"]
            == "This is a test article about Amiibo collecting."
        )
        assert result["og_type"] == "article"
        assert result["og_image"] == "https://example.com/static/image.jpg"
        assert len(result["schemas"]) == 2
        assert len(result["schemas_json"]) == 2

        # Verify JSON serialization works
        for schema_json in result["schemas_json"]:
            parsed = json.loads(schema_json)
            assert "@context" in parsed
            assert "@type" in parsed
