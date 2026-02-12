"""
Comprehensive pytest tests for amiibo scrapers.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from tracker.scrapers import NintendoDotComScraper, AmiiboLifeScraper


@pytest.fixture
def mock_database_path(tmp_path):
    """Create a temporary database path for testing."""
    db_path = tmp_path / "amiibo_database.json"
    return db_path


@pytest.fixture
def sample_amiibos():
    """Sample amiibo data for testing."""
    return [
        {
            "amiiboSeries": "Super Smash Bros.",
            "character": "Mario",
            "gameSeries": "Super Mario",
            "head": "00000000",
            "image": "https://example.com/mario.png",
            "name": "Mario",
            "release": {"na": "2014-11-21", "eu": "2014-11-28"},
            "tail": "00000002",
            "type": "Figure",
        },
        {
            "amiiboSeries": "Super Smash Bros.",
            "character": "Link",
            "gameSeries": "The Legend of Zelda",
            "head": "01010000",
            "image": "https://example.com/link.png",
            "name": "Link",
            "release": {"na": "2014-11-21"},
            "tail": "00000002",
            "type": "Figure",
        },
    ]


@pytest.fixture
def sample_scraped_data():
    """Sample data scraped from Nintendo website."""
    return [
        {
            "name": "Mario",
            "series": "Super Mario",
            "release_date": "2014-11-21",
            "image": "https://www.nintendo.com/mario.png",
        },
        {
            "name": "Link",
            "series": "The Legend of Zelda",
            "release_date": "2014-11-21",
            "image": "https://www.nintendo.com/link.png",
        },
        {
            "name": "Splatoon 3 Inkling",
            "series": "Splatoon",
            "release_date": "2026-03-15",
            "image": "https://www.nintendo.com/inkling.png",
        },
    ]


class TestNintendoDotComScraper:
    """Tests for NintendoDotComScraper class."""

    def test_initialization_defaults(self):
        """Test scraper initialization with default values."""
        scraper = NintendoDotComScraper()

        assert scraper.min_similarity == 0.6
        assert scraper.cache_hours == 6
        assert scraper.database_path.name == "amiibo_database.json"

    def test_initialization_custom_values(self):
        """Test scraper initialization with custom values."""
        scraper = NintendoDotComScraper(min_similarity=0.8, cache_hours=12)

        assert scraper.min_similarity == 0.8
        assert scraper.cache_hours == 12

    def test_should_run_no_file_exists(self, mock_database_path):
        """Test should_run returns True when database doesn't exist."""
        scraper = NintendoDotComScraper()
        scraper.database_path = mock_database_path

        assert scraper.should_run() is True

    def test_should_run_file_too_old(self, mock_database_path):
        """Test should_run returns True when file is older than cache_hours."""
        # Create an old file
        mock_database_path.write_text('{"amiibo": []}')

        # Mock the file modification time to be 10 hours ago
        with patch.object(Path, "stat") as mock_stat:
            old_time = datetime.now().timestamp() - (10 * 3600)
            mock_stat.return_value.st_mtime = old_time

            scraper = NintendoDotComScraper(cache_hours=6)
            scraper.database_path = mock_database_path

            assert scraper.should_run() is True

    def test_should_run_file_fresh(self, mock_database_path):
        """Test should_run returns False when file is newer than cache_hours."""
        # Create a fresh file
        mock_database_path.write_text('{"amiibo": []}')

        scraper = NintendoDotComScraper(cache_hours=6)
        scraper.database_path = mock_database_path

        # File was just created, should be fresh
        assert scraper.should_run() is False

    def test_normalize_name(self):
        """Test name normalization for matching."""
        scraper = NintendoDotComScraper()

        assert (
            scraper.normalize_name("Mario - Super Smash Bros.")
            == "mario super smash bros"
        )
        # Parentheses and their contents are removed
        assert scraper.normalize_name("Link (The Legend of Zelda)") == "link"
        assert scraper.normalize_name("  Multiple   Spaces  ") == "multiple spaces"

    def test_calculate_similarity_exact_substring(self):
        """Test similarity calculation for substring matches."""
        scraper = NintendoDotComScraper()

        # "mario" is substring of "mario super"
        similarity = scraper.calculate_similarity("mario", "mario super")
        # With algorithm: sequence_score * 0.6 + word_score * 0.4 + substring_bonus 0.1
        # sequence_score ~0.67, word_score 0.5, substring_bonus 0.1 -> ~0.7
        assert similarity > 0.6  # Should have decent similarity

        # Reverse
        similarity = scraper.calculate_similarity("mario super", "mario")
        assert similarity > 0.6

    def test_calculate_similarity_word_overlap(self):
        """Test similarity calculation for word overlap."""
        scraper = NintendoDotComScraper()

        # Partial word match
        similarity = scraper.calculate_similarity("super mario", "mario kart")
        # Should have decent similarity due to shared "mario"
        assert 0.3 < similarity < 0.7

    def test_calculate_similarity_no_match(self):
        """Test similarity calculation for no match."""
        scraper = NintendoDotComScraper()

        similarity = scraper.calculate_similarity("mario", "zelda")
        # Should be low but not necessarily 0 due to character-level matching
        assert similarity < 0.3

    def test_contains_date_patterns(self):
        """Test date pattern detection."""
        scraper = NintendoDotComScraper()

        assert scraper.contains_date("Available 04/02/26") is True
        assert scraper.contains_date("2026") is True
        assert scraper.contains_date("12/31/2026") is True
        assert scraper.contains_date("No date here") is False

    def test_parse_release_date_full_format(self):
        """Test parsing release date in MM/DD/YY format."""
        scraper = NintendoDotComScraper()

        result = scraper.parse_release_date("Available 04/02/26")
        assert result == "2026-04-02"

    def test_parse_release_date_full_year(self):
        """Test parsing release date in MM/DD/YYYY format."""
        scraper = NintendoDotComScraper()

        result = scraper.parse_release_date("Available 12/31/2026")
        assert result == "2026-12-31"

    def test_parse_release_date_year_only(self):
        """Test parsing release date with year only (defaults to Dec 31)."""
        scraper = NintendoDotComScraper()

        result = scraper.parse_release_date("Coming 2026")
        assert result == "2026-12-31"

    def test_parse_release_date_no_date(self):
        """Test parsing release date with no date."""
        scraper = NintendoDotComScraper()

        result = scraper.parse_release_date("No date available")
        assert result is None

    def test_clean_series(self):
        """Test series name cleaning."""
        scraper = NintendoDotComScraper()

        assert scraper.clean_series("Super Mario series") == "Super Mario"
        assert scraper.clean_series("Zelda Series") == "Zelda"
        assert scraper.clean_series("No suffix here") == "No suffix here"

    def test_is_set_or_bundle(self):
        """Test detection of sets, bundles, and grouped items."""
        scraper = NintendoDotComScraper()

        # Should identify as sets/bundles
        assert scraper.is_set_or_bundle("Card Starter Set") is True
        assert scraper.is_set_or_bundle("Cards - Series 5") is True
        assert scraper.is_set_or_bundle("Power-Up Band") is True
        assert scraper.is_set_or_bundle("Amiibo Triple Pack") is True
        assert scraper.is_set_or_bundle("Mario 3-Pack") is True
        assert scraper.is_set_or_bundle("Collection Bundle") is True

        # Should identify as individual amiibos
        assert scraper.is_set_or_bundle("Mario") is False
        assert scraper.is_set_or_bundle("Link - The Legend of Zelda") is False
        assert scraper.is_set_or_bundle("Splatoon Inkling") is False
        assert scraper.is_set_or_bundle("Super Smash Bros. Mario") is False

    def test_find_best_match_exact(self, sample_amiibos):
        """Test finding exact match."""
        scraper = NintendoDotComScraper()

        scraped_amiibo = {"name": "Mario", "release_date": "2014-11-21"}
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_partial(self, sample_amiibos):
        """Test finding partial match."""
        scraper = NintendoDotComScraper()

        # Use a closer match that will exceed the 0.6 threshold
        scraped_amiibo = {"name": "Mario Bros", "release_date": None}
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_no_match(self, sample_amiibos):
        """Test when no match is found."""
        scraper = NintendoDotComScraper()

        scraped_amiibo = {"name": "Samus", "release_date": None}
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        # With default threshold 0.6, "Samus" should not match
        assert match is None

    def test_find_best_match_with_date_boost(self, sample_amiibos):
        """Test that matching release dates boost confidence score."""
        scraper = NintendoDotComScraper()

        # Exact date match should boost score
        scraped_amiibo = {"name": "Mario", "release_date": "2014-11-21"}
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_dates_are_close(self):
        """Test date proximity detection."""
        scraper = NintendoDotComScraper()

        # Same date
        assert scraper.dates_are_close("2026-01-01", "2026-01-01") is True

        # Within 30 days
        assert scraper.dates_are_close("2026-01-01", "2026-01-15") is True
        assert scraper.dates_are_close("2026-01-15", "2026-01-01") is True

        # Beyond 30 days
        assert scraper.dates_are_close("2026-01-01", "2026-03-01") is False

        # Invalid dates
        assert scraper.dates_are_close("invalid", "2026-01-01") is False
        assert scraper.dates_are_close("2026-01-01", "invalid") is False

    def test_update_amiibo_adds_release_date(self, sample_amiibos):
        """Test updating amiibo with new release date."""
        scraper = NintendoDotComScraper()

        amiibo = {"name": "Test Amiibo", "release": {}}  # No release dates

        scraped_data = {
            "name": "Test Amiibo",
            "series": "Test Series",
            "release_date": "2026-03-15",
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is True
        assert amiibo["release"]["na"] == "2026-03-15"

    def test_update_amiibo_skips_existing_date(self, sample_amiibos):
        """Test that existing release dates are not overwritten."""
        scraper = NintendoDotComScraper()

        amiibo = sample_amiibos[0]  # Mario with existing NA date
        original_date = amiibo["release"]["na"]

        scraped_data = {
            "name": "Mario",
            "series": "Super Mario",
            "release_date": "2026-01-01",  # Different date
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is False
        assert amiibo["release"]["na"] == original_date  # Unchanged

    def test_create_placeholder_amiibo(self):
        """Test creating placeholder amiibo entry."""
        scraper = NintendoDotComScraper()

        scraped_data = {
            "name": "New Amiibo",
            "series": "New Series",
            "release_date": "2026-06-15",
        }

        placeholder = scraper.create_placeholder_amiibo(scraped_data)

        assert placeholder["name"] == "New Amiibo"
        assert placeholder["amiiboSeries"] == "New Series"
        assert placeholder["gameSeries"] == "New Series"
        assert placeholder["character"] == "New Amiibo"
        # Check that IDs are generated (not 00000000) and start with 'ff'
        assert placeholder["head"].startswith("ff")
        assert placeholder["tail"].startswith("ff")
        assert len(placeholder["head"]) == 8  # ff + 6 hex chars
        assert len(placeholder["tail"]) == 8  # ff + 6 hex chars
        # IDs should be unique based on name
        assert placeholder["head"] != placeholder["tail"]
        assert placeholder["type"] == "Figure"
        assert placeholder["release"]["na"] == "2026-06-15"
        assert placeholder["is_upcoming"] is True

    def test_load_existing_amiibos(self, mock_database_path, sample_amiibos):
        """Test loading amiibos from JSON file."""
        # Write sample data to temp file
        data = {"amiibo": sample_amiibos}
        mock_database_path.write_text(json.dumps(data))

        scraper = NintendoDotComScraper()
        scraper.database_path = mock_database_path

        loaded = scraper.load_existing_amiibos()

        assert len(loaded) == 2
        assert loaded[0]["name"] == "Mario"
        assert loaded[1]["name"] == "Link"

    def test_load_existing_amiibos_file_not_found(self, mock_database_path):
        """Test loading amiibos when file doesn't exist."""
        scraper = NintendoDotComScraper()
        scraper.database_path = mock_database_path

        loaded = scraper.load_existing_amiibos()

        assert loaded == []

    def test_save_amiibos(self, mock_database_path, sample_amiibos):
        """Test saving amiibos to JSON file."""
        scraper = NintendoDotComScraper()
        scraper.database_path = mock_database_path

        scraper.save_amiibos(sample_amiibos)

        # Verify file was written
        assert mock_database_path.exists()

        # Load and verify content
        with mock_database_path.open() as f:
            data = json.load(f)

        assert "amiibo" in data
        assert len(data["amiibo"]) == 2
        assert data["amiibo"][0]["name"] == "Mario"

    @patch("tracker.scrapers.requests.get")
    def test_scrape_nintendo_amiibos_success(self, mock_get):
        """Test successful scraping from Nintendo website."""
        # Mock HTML response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <a href="/us/amiibo/detail/mario/" aria-label="Mario">
                <p>Super Mario series</p>
                <p>Available 04/02/26</p>
            </a>
            <a href="/us/amiibo/detail/link/" aria-label="Link">
                <p>The Legend of Zelda series</p>
                <p>2026</p>
            </a>
        </html>
        """
        mock_get.return_value = mock_response

        scraper = NintendoDotComScraper()
        result = scraper.scrape_nintendo_amiibos()

        assert len(result) == 2
        assert result[0]["name"] == "Mario"
        assert result[0]["series"] == "Super Mario"
        assert result[0]["release_date"] == "2026-04-02"
        assert result[1]["name"] == "Link"
        assert result[1]["series"] == "The Legend of Zelda"

    @patch("tracker.scrapers.requests.get")
    def test_scrape_nintendo_amiibos_network_error(self, mock_get):
        """Test scraping with network error."""
        import requests

        mock_get.side_effect = requests.RequestException("Network error")

        scraper = NintendoDotComScraper()
        result = scraper.scrape_nintendo_amiibos()

        assert result == []

    @patch.object(NintendoDotComScraper, "scrape_nintendo_amiibos")
    @patch.object(NintendoDotComScraper, "load_existing_amiibos")
    @patch.object(NintendoDotComScraper, "save_amiibos")
    @patch.object(NintendoDotComScraper, "should_run")
    def test_run_full_workflow(
        self,
        mock_should_run,
        mock_save,
        mock_load,
        mock_scrape,
        sample_amiibos,
        sample_scraped_data,
    ):
        """Test full scraper workflow."""
        mock_should_run.return_value = True
        mock_scrape.return_value = sample_scraped_data
        mock_load.return_value = sample_amiibos.copy()

        scraper = NintendoDotComScraper()
        result = scraper.run()

        assert result["status"] == "success"
        assert result["matched"] == 2  # Mario and Link matched
        assert result["new"] == 1  # Splatoon 3 Inkling is new
        assert mock_save.called

    @patch.object(NintendoDotComScraper, "should_run")
    def test_run_skipped_due_to_cache(self, mock_should_run):
        """Test that run is skipped when cache is valid."""
        mock_should_run.return_value = False

        scraper = NintendoDotComScraper()
        result = scraper.run(force=False)

        assert result["status"] == "skipped"
        assert result["reason"] == "cache_valid"

    @patch.object(NintendoDotComScraper, "should_run")
    @patch.object(NintendoDotComScraper, "scrape_nintendo_amiibos")
    def test_run_force_bypasses_cache(self, mock_scrape, mock_should_run):
        """Test that force=True bypasses cache check."""
        mock_should_run.return_value = False  # Cache says skip
        mock_scrape.return_value = []

        scraper = NintendoDotComScraper()
        result = scraper.run(force=True)

        # Should run despite cache
        assert mock_scrape.called
        assert result["status"] == "error"  # No amiibos scraped

    @patch.object(NintendoDotComScraper, "scrape_nintendo_amiibos")
    @patch.object(NintendoDotComScraper, "should_run")
    def test_run_handles_scraping_error(self, mock_should_run, mock_scrape):
        """Test that run handles scraping errors gracefully."""
        mock_should_run.return_value = True
        mock_scrape.side_effect = Exception("Scraping failed")

        scraper = NintendoDotComScraper()
        result = scraper.run()

        assert result["status"] == "error"
        assert "Scraping failed" in result["message"]


class TestScraperIntegration:
    """Integration tests for the scraper."""

    @patch("tracker.scrapers.requests.get")
    def test_end_to_end_scraping(self, mock_get, tmp_path):
        """Test complete end-to-end scraping workflow."""
        # Setup
        db_path = tmp_path / "amiibo_database.json"
        existing_data = {
            "amiibo": [
                {
                    "name": "Mario",
                    "character": "Mario",
                    "gameSeries": "Super Mario",
                    "head": "00000000",
                    "tail": "00000002",
                    "release": {"eu": "2014-11-28"},  # No NA date
                    "type": "Figure",
                }
            ]
        }
        db_path.write_text(json.dumps(existing_data))

        # Mock Nintendo website response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <a href="/us/amiibo/detail/mario/" aria-label="Mario">
                <p>Super Mario series</p>
                <p>Available 11/21/2014</p>
            </a>
            <a href="/us/amiibo/detail/luigi/" aria-label="Luigi">
                <p>Super Mario series</p>
                <p>2014</p>
            </a>
        </html>
        """
        mock_get.return_value = mock_response

        # Run scraper
        scraper = NintendoDotComScraper()
        scraper.database_path = db_path
        result = scraper.run(force=True)

        # Verify results
        assert result["status"] == "success"
        assert result["matched"] == 1  # Mario matched
        assert result["new"] == 1  # Luigi is new

        # Load saved data
        with db_path.open() as f:
            saved_data = json.load(f)

        # Verify Mario got NA release date
        mario = next(a for a in saved_data["amiibo"] if a["name"] == "Mario")
        assert mario["release"]["na"] == "2014-11-21"

        # Verify Luigi was added
        luigi = next(a for a in saved_data["amiibo"] if a["name"] == "Luigi")
        assert luigi["is_upcoming"] is True
        assert luigi["head"].startswith("ff")  # Placeholder with unique ID


class TestImageURLCleaning:
    """Tests for Nintendo image URL cleaning."""

    def test_clean_amiibo_image_url(self):
        """Test cleaning Nintendo amiibo image URLs."""
        scraper = NintendoDotComScraper()

        # Test URL with complex parameters
        original = "https://assets.nintendo.com/image/upload/ar_16:9,b_auto:border,c_lpad/b_black/f_auto/q_auto/dpr_1.5/amiibo/Kirby%20Air%20RIders/chef-kawasaki-and-hop-star-figure"
        expected = "https://assets.nintendo.com/image/upload/f_png/q_auto/amiibo/Kirby%20Air%20RIders/chef-kawasaki-and-hop-star-figure"

        result = scraper.clean_amiibo_image_url(original)
        assert result == expected

    def test_clean_amiibo_image_url_various_params(self):
        """Test cleaning URLs with different parameter combinations."""
        scraper = NintendoDotComScraper()

        # Different parameters before /amiibo/
        original = "https://assets.nintendo.com/image/upload/c_fill,w_300,h_300/f_auto/amiibo/mario/figure"
        expected = (
            "https://assets.nintendo.com/image/upload/f_png/q_auto/amiibo/mario/figure"
        )

        result = scraper.clean_amiibo_image_url(original)
        assert result == expected

    def test_clean_amiibo_image_url_already_clean(self):
        """Test that already clean URLs pass through correctly."""
        scraper = NintendoDotComScraper()

        # URL already in desired format
        original = (
            "https://assets.nintendo.com/image/upload/f_png/q_auto/amiibo/mario/figure"
        )
        expected = (
            "https://assets.nintendo.com/image/upload/f_png/q_auto/amiibo/mario/figure"
        )

        result = scraper.clean_amiibo_image_url(original)
        assert result == expected


class TestAmiiboLifeScraper:
    """Tests for AmiiboLifeScraper class."""

    def test_initialization_defaults(self):
        """Test scraper initialization with default values."""
        scraper = AmiiboLifeScraper()

        assert scraper.min_similarity == 0.6
        assert scraper.cache_hours == 6
        assert scraper.database_path.name == "amiibo_database.json"
        assert scraper.current_year == datetime.now().year

    def test_initialization_custom_values(self):
        """Test scraper initialization with custom values."""
        scraper = AmiiboLifeScraper(min_similarity=0.8, cache_hours=12)

        assert scraper.min_similarity == 0.8
        assert scraper.cache_hours == 12

    def test_should_run_no_file_exists(self, mock_database_path):
        """Test should_run returns True when database doesn't exist."""
        scraper = AmiiboLifeScraper()
        scraper.database_path = mock_database_path

        assert scraper.should_run() is True

    def test_should_run_file_too_old(self, mock_database_path):
        """Test should_run returns True when file is older than cache_hours."""
        # Create an old file
        mock_database_path.write_text('{"amiibo": []}')

        # Mock the file modification time to be 10 hours ago
        with patch.object(Path, "stat") as mock_stat:
            old_time = datetime.now().timestamp() - (10 * 3600)
            mock_stat.return_value.st_mtime = old_time

            scraper = AmiiboLifeScraper(cache_hours=6)
            scraper.database_path = mock_database_path

            assert scraper.should_run() is True

    def test_should_run_file_fresh(self, mock_database_path):
        """Test should_run returns False when file is newer than cache_hours."""
        # Create a fresh file
        mock_database_path.write_text('{"amiibo": []}')

        scraper = AmiiboLifeScraper(cache_hours=6)
        scraper.database_path = mock_database_path

        # File was just created, should be fresh
        assert scraper.should_run() is False

    def test_normalize_name(self):
        """Test name normalization for matching."""
        scraper = AmiiboLifeScraper()

        assert (
            scraper.normalize_name("Mario - Super Smash Bros.")
            == "mario super smash bros"
        )
        assert scraper.normalize_name("Link (The Legend of Zelda)") == "link"
        assert scraper.normalize_name("  Multiple   Spaces  ") == "multiple spaces"

    def test_calculate_similarity_exact_substring(self):
        """Test similarity calculation for substring matches."""
        scraper = AmiiboLifeScraper()

        similarity = scraper.calculate_similarity("mario", "mario super")
        assert similarity > 0.6

        similarity = scraper.calculate_similarity("mario super", "mario")
        assert similarity > 0.6

    def test_clean_series(self):
        """Test series name cleaning."""
        scraper = AmiiboLifeScraper()

        assert scraper.clean_series("Super Mario series") == "Super Mario"
        assert scraper.clean_series("Zelda Series") == "Zelda"
        assert scraper.clean_series("No suffix here") == "No suffix here"

    def test_is_set_or_bundle(self):
        """Test detection of sets, bundles, and grouped items."""
        scraper = AmiiboLifeScraper()

        # Should identify as sets/bundles
        assert scraper.is_set_or_bundle("Card Starter Set") is True
        assert scraper.is_set_or_bundle("Cards - Series 5") is True
        assert scraper.is_set_or_bundle("Power-Up Band") is True
        assert scraper.is_set_or_bundle("Street Fighter 6 Starter Set") is True

        # Should identify as individual amiibos
        assert scraper.is_set_or_bundle("Mario") is False
        assert scraper.is_set_or_bundle("Peach") is False

    def test_find_best_match_exact(self, sample_amiibos):
        """Test finding exact match."""
        scraper = AmiiboLifeScraper()

        scraped_amiibo = {
            "name": "Mario",
            "release_dates": {"na": "2014-11-21"},
        }
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_with_multiple_regions(self, sample_amiibos):
        """Test finding match with multiple release date regions."""
        scraper = AmiiboLifeScraper()

        scraped_amiibo = {
            "name": "Mario",
            "release_dates": {
                "na": "2014-11-21",
                "eu": "2014-11-28",
                "jp": "2014-12-06",
            },
        }
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_no_match(self, sample_amiibos):
        """Test when no match is found."""
        scraper = AmiiboLifeScraper()

        scraped_amiibo = {"name": "Samus", "release_dates": {}}
        match = scraper.find_best_match(scraped_amiibo, sample_amiibos)
        assert match is None

    def test_dates_are_close(self):
        """Test date proximity detection."""
        scraper = AmiiboLifeScraper()

        # Same date
        assert scraper.dates_are_close("2026-01-01", "2026-01-01") is True

        # Within 30 days
        assert scraper.dates_are_close("2026-01-01", "2026-01-15") is True

        # Beyond 30 days
        assert scraper.dates_are_close("2026-01-01", "2026-03-01") is False

        # Invalid dates
        assert scraper.dates_are_close("invalid", "2026-01-01") is False

    def test_update_amiibo_adds_release_dates(self):
        """Test updating amiibo with new release dates from multiple regions."""
        scraper = AmiiboLifeScraper()

        amiibo = {"name": "Test Amiibo", "release": {}}

        scraped_data = {
            "name": "Test Amiibo",
            "series": "Test Series",
            "release_dates": {
                "na": "2026-03-15",
                "eu": "2026-03-20",
                "jp": "2026-03-10",
            },
            "image": "",
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is True
        assert amiibo["release"]["na"] == "2026-03-15"
        assert amiibo["release"]["eu"] == "2026-03-20"
        assert amiibo["release"]["jp"] == "2026-03-10"

    def test_update_amiibo_adds_image(self):
        """Test updating amiibo with image URL."""
        scraper = AmiiboLifeScraper()

        amiibo = {"name": "Test Amiibo", "release": {}}

        scraped_data = {
            "name": "Test Amiibo",
            "series": "Test Series",
            "release_dates": {},
            "image": "https://amiibo.life/assets/figures/test.png",
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is True
        assert amiibo["image"] == "https://amiibo.life/assets/figures/test.png"

    def test_update_amiibo_skips_existing_image(self):
        """Test that existing images are not overwritten."""
        scraper = AmiiboLifeScraper()

        amiibo = {
            "name": "Test Amiibo",
            "release": {},
            "image": "https://existing.com/image.png",
        }

        scraped_data = {
            "name": "Test Amiibo",
            "series": "Test Series",
            "release_dates": {},
            "image": "https://amiibo.life/assets/figures/new.png",
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is False
        assert amiibo["image"] == "https://existing.com/image.png"

    def test_create_placeholder_amiibo_with_type(self):
        """Test creating placeholder amiibo with specified type."""
        scraper = AmiiboLifeScraper()

        scraped_data = {
            "name": "New Card Amiibo",
            "series": "Animal Crossing",
            "release_dates": {"na": "2026-06-15"},
            "image": "https://amiibo.life/assets/figures/test.png",
            "type": "Card",
        }

        placeholder = scraper.create_placeholder_amiibo(scraped_data)

        assert placeholder["name"] == "New Card Amiibo"
        assert placeholder["type"] == "Card"
        assert placeholder["amiiboSeries"] == "Animal Crossing"
        assert placeholder["head"].startswith("ff")
        assert placeholder["tail"].startswith("ff")
        assert placeholder["is_upcoming"] is True
        assert placeholder["release"]["na"] == "2026-06-15"
        assert placeholder["image"] == "https://amiibo.life/assets/figures/test.png"

    def test_load_existing_amiibos(self, mock_database_path, sample_amiibos):
        """Test loading amiibos from JSON file."""
        data = {"amiibo": sample_amiibos}
        mock_database_path.write_text(json.dumps(data))

        scraper = AmiiboLifeScraper()
        scraper.database_path = mock_database_path

        loaded = scraper.load_existing_amiibos()

        assert len(loaded) == 2
        assert loaded[0]["name"] == "Mario"
        assert loaded[1]["name"] == "Link"

    def test_save_amiibos(self, mock_database_path, sample_amiibos):
        """Test saving amiibos to JSON file."""
        scraper = AmiiboLifeScraper()
        scraper.database_path = mock_database_path

        scraper.save_amiibos(sample_amiibos)

        assert mock_database_path.exists()

        with mock_database_path.open() as f:
            data = json.load(f)

        assert "amiibo" in data
        assert len(data["amiibo"]) == 2

    @patch("tracker.scrapers.requests.get")
    def test_scrape_amiibo_life_success(self, mock_get):
        """Test successful scraping from amiibo.life website."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <tr>
                <td>
                    <a href="/amiibo/super-smash-bros/mario">
                        <div class="figure-card row lazy" data-src="/assets/figures/amiibo/super-smash-bros/mario.png">
                            <p class="name">Mario</p>
                            <p class="series">Super Smash Bros. series<br />amiibo figure</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="North America" class="region_flag" src="/assets/regions/na.png" />
                            <time datetime="2014-11-21">2014 Nov 21</time>
                        </li>
                        <li>
                            <img title="Europe" class="region_flag" src="/assets/regions/eu.png" />
                            <time datetime="2014-11-28">2014 Nov 28</time>
                        </li>
                    </ul>
                </td>
            </tr>
            <tr>
                <td>
                    <a href="/amiibo/splatoon/inkling-girl">
                        <div class="figure-card row lazy" data-src="/assets/figures/amiibo/splatoon/inkling.png">
                            <p class="name">Inkling Girl</p>
                            <p class="series">Splatoon series<br />amiibo figure</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="Japan" class="region_flag" src="/assets/regions/jp.png" />
                            <time datetime="2015-05-28">2015 May 28</time>
                        </li>
                    </ul>
                </td>
            </tr>
        </html>
        """
        mock_get.return_value = mock_response

        scraper = AmiiboLifeScraper()
        result = scraper.scrape_amiibo_life()

        assert len(result) == 2
        assert result[0]["name"] == "Mario"
        assert result[0]["series"] == "Super Smash Bros."
        assert result[0]["type"] == "Figure"
        assert result[0]["release_dates"]["na"] == "2014-11-21"
        assert result[0]["release_dates"]["eu"] == "2014-11-28"
        assert (
            result[0]["image"]
            == "https://amiibo.life/assets/figures/amiibo/super-smash-bros/mario.png"
        )

        assert result[1]["name"] == "Inkling Girl"
        assert result[1]["series"] == "Splatoon"
        assert result[1]["release_dates"]["jp"] == "2015-05-28"

    @patch("tracker.scrapers.requests.get")
    def test_scrape_amiibo_life_network_error(self, mock_get):
        """Test scraping with network error."""
        import requests

        mock_get.side_effect = requests.RequestException("Network error")

        scraper = AmiiboLifeScraper()
        result = scraper.scrape_amiibo_life()

        assert result == []

    @patch("tracker.scrapers.requests.get")
    def test_scrape_amiibo_life_skips_games(self, mock_get):
        """Test that game cards are skipped (only figure-card divs are processed)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <tr>
                <td>
                    <a href="/games/switch/mario-kart-8">
                        <div class="game-card row lazy" data-src="/assets/games/mario-kart.png">
                            <p class="name">Mario Kart 8</p>
                            <p class="system">amiibo-compatible<br />Nintendo Switch game</p>
                        </div>
                    </a>
                </td>
            </tr>
            <tr>
                <td>
                    <a href="/amiibo/super-mario/mario">
                        <div class="figure-card row lazy" data-src="/assets/figures/amiibo/mario.png">
                            <p class="name">Mario</p>
                            <p class="series">Super Mario series<br />amiibo figure</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="North America" class="region_flag" />
                            <time datetime="2015-03-20">2015 Mar 20</time>
                        </li>
                    </ul>
                </td>
            </tr>
        </html>
        """
        mock_get.return_value = mock_response

        scraper = AmiiboLifeScraper()
        result = scraper.scrape_amiibo_life()

        # Should only have Mario, not Mario Kart 8
        assert len(result) == 1
        assert result[0]["name"] == "Mario"

    @patch("tracker.scrapers.requests.get")
    def test_scrape_amiibo_life_handles_cards(self, mock_get):
        """Test that amiibo cards are properly identified."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <tr>
                <td>
                    <a href="/amiibo/animal-crossing/isabelle-card">
                        <div class="figure-card row lazy" data-src="/assets/figures/amiibo/isabelle.png">
                            <p class="name">Isabelle</p>
                            <p class="series">Animal Crossing series<br />amiibo cards</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="North America" class="region_flag" />
                            <time datetime="2015-09-25">2015 Sep 25</time>
                        </li>
                    </ul>
                </td>
            </tr>
        </html>
        """
        mock_get.return_value = mock_response

        scraper = AmiiboLifeScraper()
        result = scraper.scrape_amiibo_life()

        assert len(result) == 1
        assert result[0]["name"] == "Isabelle"
        assert result[0]["type"] == "Card"
        assert result[0]["series"] == "Animal Crossing"

    @patch.object(AmiiboLifeScraper, "scrape_amiibo_life")
    @patch.object(AmiiboLifeScraper, "load_existing_amiibos")
    @patch.object(AmiiboLifeScraper, "save_amiibos")
    @patch.object(AmiiboLifeScraper, "should_run")
    def test_run_full_workflow(
        self,
        mock_should_run,
        mock_save,
        mock_load,
        mock_scrape,
        sample_amiibos,
    ):
        """Test full scraper workflow."""
        mock_should_run.return_value = True

        scraped_data = [
            {
                "name": "Mario",
                "series": "Super Mario",
                "release_dates": {"na": "2014-11-21"},
                "image": "https://amiibo.life/mario.png",
                "type": "Figure",
            },
            {
                "name": "New Amiibo",
                "series": "New Series",
                "release_dates": {"na": "2026-06-15"},
                "image": "https://amiibo.life/new.png",
                "type": "Figure",
            },
        ]

        mock_scrape.return_value = scraped_data
        mock_load.return_value = sample_amiibos.copy()

        scraper = AmiiboLifeScraper()
        result = scraper.run()

        assert result["status"] == "success"
        assert result["matched"] == 1  # Mario matched
        assert result["new"] == 1  # New Amiibo is new
        assert mock_save.called

    @patch.object(AmiiboLifeScraper, "should_run")
    def test_run_skipped_due_to_cache(self, mock_should_run):
        """Test that run is skipped when cache is valid."""
        mock_should_run.return_value = False

        scraper = AmiiboLifeScraper()
        result = scraper.run(force=False)

        assert result["status"] == "skipped"
        assert result["reason"] == "cache_valid"

    @patch.object(AmiiboLifeScraper, "should_run")
    @patch.object(AmiiboLifeScraper, "scrape_amiibo_life")
    def test_run_force_bypasses_cache(self, mock_scrape, mock_should_run):
        """Test that force=True bypasses cache check."""
        mock_should_run.return_value = False
        mock_scrape.return_value = []

        scraper = AmiiboLifeScraper()
        result = scraper.run(force=True)

        assert mock_scrape.called
        assert result["status"] == "error"  # No amiibos scraped


class TestAmiiboLifeScraperIntegration:
    """Integration tests for AmiiboLifeScraper."""

    @patch("tracker.scrapers.requests.get")
    def test_end_to_end_scraping(self, mock_get, tmp_path):
        """Test complete end-to-end scraping workflow."""
        db_path = tmp_path / "amiibo_database.json"
        existing_data = {
            "amiibo": [
                {
                    "name": "Mario",
                    "character": "Mario",
                    "gameSeries": "Super Mario",
                    "head": "00000000",
                    "tail": "00000002",
                    "release": {"eu": "2014-11-28"},  # No NA date
                    "type": "Figure",
                }
            ]
        }
        db_path.write_text(json.dumps(existing_data))

        # Mock amiibo.life response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <tr>
                <td>
                    <a href="/amiibo/super-smash-bros/mario">
                        <div class="figure-card row lazy" data-src="/assets/figures/mario.png">
                            <p class="name">Mario</p>
                            <p class="series">Super Mario series<br />amiibo figure</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="North America" class="region_flag" />
                            <time datetime="2014-11-21">2014 Nov 21</time>
                        </li>
                    </ul>
                </td>
            </tr>
            <tr>
                <td>
                    <a href="/amiibo/splatoon/inkling">
                        <div class="figure-card row lazy" data-src="/assets/figures/inkling.png">
                            <p class="name">Inkling</p>
                            <p class="series">Splatoon series<br />amiibo figure</p>
                        </div>
                    </a>
                </td>
                <td class="release_dates_cell">
                    <ul class="release_dates">
                        <li>
                            <img title="North America" class="region_flag" />
                            <time datetime="2015-05-29">2015 May 29</time>
                        </li>
                    </ul>
                </td>
            </tr>
        </html>
        """
        mock_get.return_value = mock_response

        # Run scraper
        scraper = AmiiboLifeScraper()
        scraper.database_path = db_path
        result = scraper.run(force=True)

        # Verify results
        assert result["status"] == "success"
        assert result["matched"] == 1  # Mario matched
        assert result["new"] == 1  # Inkling is new

        # Load saved data
        with db_path.open() as f:
            saved_data = json.load(f)

        # Verify Mario got NA release date
        mario = next(a for a in saved_data["amiibo"] if a["name"] == "Mario")
        assert mario["release"]["na"] == "2014-11-21"

        # Verify Inkling was added
        inkling = next(a for a in saved_data["amiibo"] if a["name"] == "Inkling")
        assert inkling["is_upcoming"] is True
        assert inkling["head"].startswith("ff")

    def test_update_amiibo_only_updates_upcoming(self):
        """Test that release dates are only updated for upcoming amiibos."""
        scraper = AmiiboLifeScraper()

        # Non-upcoming amiibo (official from AmiiboAPI)
        existing_amiibo = {
            "name": "Mario",
            "release": {"na": "2014-11-21"},
            "is_upcoming": False,
        }

        scraped_data = {
            "name": "Mario",
            "series": "Super Mario",
            "release_dates": {"eu": "2014-11-28"},  # New EU date
            "image": "",
        }

        updated = scraper.update_amiibo(existing_amiibo, scraped_data)

        # Should NOT update because is_upcoming=False
        assert updated is False
        assert "eu" not in existing_amiibo["release"]

    def test_update_amiibo_updates_upcoming_dates(self):
        """Test that release dates ARE updated for upcoming amiibos."""
        scraper = AmiiboLifeScraper()

        # Upcoming amiibo (newly scraped)
        existing_amiibo = {
            "name": "New Amiibo",
            "release": {},
            "is_upcoming": True,
        }

        scraped_data = {
            "name": "New Amiibo",
            "series": "New Series",
            "release_dates": {
                "na": "2026-06-15",
                "eu": "2026-06-20",
            },
            "image": "",
        }

        updated = scraper.update_amiibo(existing_amiibo, scraped_data)

        # Should update because is_upcoming=True
        assert updated is True
        assert existing_amiibo["release"]["na"] == "2026-06-15"
        assert existing_amiibo["release"]["eu"] == "2026-06-20"
