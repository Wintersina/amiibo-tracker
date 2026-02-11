"""
Comprehensive pytest tests for Nintendo amiibo scraper.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from tracker.scrapers import NintendoAmiiboScraper


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
        },
        {
            "name": "Link",
            "series": "The Legend of Zelda",
            "release_date": "2014-11-21",
        },
        {
            "name": "Splatoon 3 Inkling",
            "series": "Splatoon",
            "release_date": "2026-03-15",
        },
    ]


class TestNintendoAmiiboScraper:
    """Tests for NintendoAmiiboScraper class."""

    def test_initialization_defaults(self):
        """Test scraper initialization with default values."""
        scraper = NintendoAmiiboScraper()

        assert scraper.min_similarity == 0.6
        assert scraper.cache_hours == 6
        assert scraper.database_path.name == "amiibo_database.json"

    def test_initialization_custom_values(self):
        """Test scraper initialization with custom values."""
        scraper = NintendoAmiiboScraper(min_similarity=0.8, cache_hours=12)

        assert scraper.min_similarity == 0.8
        assert scraper.cache_hours == 12

    def test_should_run_no_file_exists(self, mock_database_path):
        """Test should_run returns True when database doesn't exist."""
        scraper = NintendoAmiiboScraper()
        scraper.database_path = mock_database_path

        assert scraper.should_run() is True

    def test_should_run_file_too_old(self, mock_database_path):
        """Test should_run returns True when file is older than cache_hours."""
        # Create an old file
        mock_database_path.write_text('{"amiibo": []}')

        # Mock the file modification time to be 10 hours ago
        with patch.object(Path, 'stat') as mock_stat:
            old_time = datetime.now().timestamp() - (10 * 3600)
            mock_stat.return_value.st_mtime = old_time

            scraper = NintendoAmiiboScraper(cache_hours=6)
            scraper.database_path = mock_database_path

            assert scraper.should_run() is True

    def test_should_run_file_fresh(self, mock_database_path):
        """Test should_run returns False when file is newer than cache_hours."""
        # Create a fresh file
        mock_database_path.write_text('{"amiibo": []}')

        scraper = NintendoAmiiboScraper(cache_hours=6)
        scraper.database_path = mock_database_path

        # File was just created, should be fresh
        assert scraper.should_run() is False

    def test_normalize_name(self):
        """Test name normalization for matching."""
        scraper = NintendoAmiiboScraper()

        assert scraper.normalize_name("Mario - Super Smash Bros.") == "mario super smash bros"
        assert scraper.normalize_name("Link (The Legend of Zelda)") == "link the legend of zelda"
        assert scraper.normalize_name("  Multiple   Spaces  ") == "multiple spaces"

    def test_calculate_similarity_exact_substring(self):
        """Test similarity calculation for substring matches."""
        scraper = NintendoAmiiboScraper()

        # "mario" is substring of "mario super"
        similarity = scraper.calculate_similarity("mario", "mario super")
        assert similarity == 0.9

        # Reverse
        similarity = scraper.calculate_similarity("mario super", "mario")
        assert similarity == 0.9

    def test_calculate_similarity_word_overlap(self):
        """Test similarity calculation for word overlap."""
        scraper = NintendoAmiiboScraper()

        # One word in common out of three total unique words
        similarity = scraper.calculate_similarity("super mario", "mario kart")
        assert similarity == 1/3  # intersection: {mario} / union: {super, mario, kart}

    def test_calculate_similarity_no_match(self):
        """Test similarity calculation for no match."""
        scraper = NintendoAmiiboScraper()

        similarity = scraper.calculate_similarity("mario", "zelda")
        assert similarity == 0

    def test_contains_date_patterns(self):
        """Test date pattern detection."""
        scraper = NintendoAmiiboScraper()

        assert scraper.contains_date("Available 04/02/26") is True
        assert scraper.contains_date("2026") is True
        assert scraper.contains_date("12/31/2026") is True
        assert scraper.contains_date("No date here") is False

    def test_parse_release_date_full_format(self):
        """Test parsing release date in MM/DD/YY format."""
        scraper = NintendoAmiiboScraper()

        result = scraper.parse_release_date("Available 04/02/26")
        assert result == "2026-04-02"

    def test_parse_release_date_full_year(self):
        """Test parsing release date in MM/DD/YYYY format."""
        scraper = NintendoAmiiboScraper()

        result = scraper.parse_release_date("Available 12/31/2026")
        assert result == "2026-12-31"

    def test_parse_release_date_year_only(self):
        """Test parsing release date with year only."""
        scraper = NintendoAmiiboScraper()

        result = scraper.parse_release_date("Coming 2026")
        assert result == "2026-01-01"

    def test_parse_release_date_no_date(self):
        """Test parsing release date with no date."""
        scraper = NintendoAmiiboScraper()

        result = scraper.parse_release_date("No date available")
        assert result is None

    def test_clean_series(self):
        """Test series name cleaning."""
        scraper = NintendoAmiiboScraper()

        assert scraper.clean_series("Super Mario series") == "Super Mario"
        assert scraper.clean_series("Zelda Series") == "Zelda"
        assert scraper.clean_series("No suffix here") == "No suffix here"

    def test_find_best_match_exact(self, sample_amiibos):
        """Test finding exact match."""
        scraper = NintendoAmiiboScraper()

        match = scraper.find_best_match("Mario", sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_partial(self, sample_amiibos):
        """Test finding partial match."""
        scraper = NintendoAmiiboScraper()

        match = scraper.find_best_match("Super Smash Bros Mario", sample_amiibos)
        assert match is not None
        assert match["name"] == "Mario"

    def test_find_best_match_no_match(self, sample_amiibos):
        """Test when no match is found."""
        scraper = NintendoAmiiboScraper()

        match = scraper.find_best_match("Samus", sample_amiibos)
        # With default threshold 0.6, "Samus" should not match
        assert match is None

    def test_update_amiibo_adds_release_date(self, sample_amiibos):
        """Test updating amiibo with new release date."""
        scraper = NintendoAmiiboScraper()

        amiibo = {
            "name": "Test Amiibo",
            "release": {}  # No release dates
        }

        scraped_data = {
            "name": "Test Amiibo",
            "series": "Test Series",
            "release_date": "2026-03-15"
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is True
        assert amiibo["release"]["na"] == "2026-03-15"

    def test_update_amiibo_skips_existing_date(self, sample_amiibos):
        """Test that existing release dates are not overwritten."""
        scraper = NintendoAmiiboScraper()

        amiibo = sample_amiibos[0]  # Mario with existing NA date
        original_date = amiibo["release"]["na"]

        scraped_data = {
            "name": "Mario",
            "series": "Super Mario",
            "release_date": "2026-01-01"  # Different date
        }

        updated = scraper.update_amiibo(amiibo, scraped_data)

        assert updated is False
        assert amiibo["release"]["na"] == original_date  # Unchanged

    def test_create_placeholder_amiibo(self):
        """Test creating placeholder amiibo entry."""
        scraper = NintendoAmiiboScraper()

        scraped_data = {
            "name": "New Amiibo",
            "series": "New Series",
            "release_date": "2026-06-15"
        }

        placeholder = scraper.create_placeholder_amiibo(scraped_data)

        assert placeholder["name"] == "New Amiibo"
        assert placeholder["amiiboSeries"] == "New Series"
        assert placeholder["gameSeries"] == "New Series"
        assert placeholder["character"] == "New Amiibo"
        assert placeholder["head"] == "00000000"
        assert placeholder["tail"] == "00000000"
        assert placeholder["type"] == "Figure"
        assert placeholder["release"]["na"] == "2026-06-15"
        assert placeholder["_needs_backfill"] is True

    def test_load_existing_amiibos(self, mock_database_path, sample_amiibos):
        """Test loading amiibos from JSON file."""
        # Write sample data to temp file
        data = {"amiibo": sample_amiibos}
        mock_database_path.write_text(json.dumps(data))

        scraper = NintendoAmiiboScraper()
        scraper.database_path = mock_database_path

        loaded = scraper.load_existing_amiibos()

        assert len(loaded) == 2
        assert loaded[0]["name"] == "Mario"
        assert loaded[1]["name"] == "Link"

    def test_load_existing_amiibos_file_not_found(self, mock_database_path):
        """Test loading amiibos when file doesn't exist."""
        scraper = NintendoAmiiboScraper()
        scraper.database_path = mock_database_path

        loaded = scraper.load_existing_amiibos()

        assert loaded == []

    def test_save_amiibos(self, mock_database_path, sample_amiibos):
        """Test saving amiibos to JSON file."""
        scraper = NintendoAmiiboScraper()
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

    @patch('tracker.scrapers.requests.get')
    def test_scrape_nintendo_amiibos_success(self, mock_get):
        """Test successful scraping from Nintendo website."""
        # Mock HTML response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"""
        <html>
            <a href="/us/amiibo/detail/mario/">
                <h2>Mario</h2>
                <h3>Super Mario series</h3>
                <p>Available 04/02/26</p>
            </a>
            <a href="/us/amiibo/detail/link/">
                <h2>Link</h2>
                <h3>The Legend of Zelda series</h3>
                <p>2026</p>
            </a>
        </html>
        """
        mock_get.return_value = mock_response

        scraper = NintendoAmiiboScraper()
        result = scraper.scrape_nintendo_amiibos()

        assert len(result) == 2
        assert result[0]["name"] == "Mario"
        assert result[0]["series"] == "Super Mario"
        assert result[0]["release_date"] == "2026-04-02"
        assert result[1]["name"] == "Link"
        assert result[1]["series"] == "The Legend of Zelda"

    @patch('tracker.scrapers.requests.get')
    def test_scrape_nintendo_amiibos_network_error(self, mock_get):
        """Test scraping with network error."""
        import requests
        mock_get.side_effect = requests.RequestException("Network error")

        scraper = NintendoAmiiboScraper()
        result = scraper.scrape_nintendo_amiibos()

        assert result == []

    @patch.object(NintendoAmiiboScraper, 'scrape_nintendo_amiibos')
    @patch.object(NintendoAmiiboScraper, 'load_existing_amiibos')
    @patch.object(NintendoAmiiboScraper, 'save_amiibos')
    @patch.object(NintendoAmiiboScraper, 'should_run')
    def test_run_full_workflow(self, mock_should_run, mock_save, mock_load, mock_scrape,
                              sample_amiibos, sample_scraped_data):
        """Test full scraper workflow."""
        mock_should_run.return_value = True
        mock_scrape.return_value = sample_scraped_data
        mock_load.return_value = sample_amiibos.copy()

        scraper = NintendoAmiiboScraper()
        result = scraper.run()

        assert result["status"] == "success"
        assert result["matched"] == 2  # Mario and Link matched
        assert result["new"] == 1  # Splatoon 3 Inkling is new
        assert mock_save.called

    @patch.object(NintendoAmiiboScraper, 'should_run')
    def test_run_skipped_due_to_cache(self, mock_should_run):
        """Test that run is skipped when cache is valid."""
        mock_should_run.return_value = False

        scraper = NintendoAmiiboScraper()
        result = scraper.run(force=False)

        assert result["status"] == "skipped"
        assert result["reason"] == "cache_valid"

    @patch.object(NintendoAmiiboScraper, 'should_run')
    @patch.object(NintendoAmiiboScraper, 'scrape_nintendo_amiibos')
    def test_run_force_bypasses_cache(self, mock_scrape, mock_should_run):
        """Test that force=True bypasses cache check."""
        mock_should_run.return_value = False  # Cache says skip
        mock_scrape.return_value = []

        scraper = NintendoAmiiboScraper()
        result = scraper.run(force=True)

        # Should run despite cache
        assert mock_scrape.called
        assert result["status"] == "error"  # No amiibos scraped

    @patch.object(NintendoAmiiboScraper, 'scrape_nintendo_amiibos')
    @patch.object(NintendoAmiiboScraper, 'should_run')
    def test_run_handles_scraping_error(self, mock_should_run, mock_scrape):
        """Test that run handles scraping errors gracefully."""
        mock_should_run.return_value = True
        mock_scrape.side_effect = Exception("Scraping failed")

        scraper = NintendoAmiiboScraper()
        result = scraper.run()

        assert result["status"] == "error"
        assert "Scraping failed" in result["message"]


class TestScraperIntegration:
    """Integration tests for the scraper."""

    @patch('tracker.scrapers.requests.get')
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
            <a href="/us/amiibo/detail/mario/">
                <h2>Mario</h2>
                <p>Super Mario series</p>
                <p>Available 11/21/2014</p>
            </a>
            <a href="/us/amiibo/detail/luigi/">
                <h2>Luigi</h2>
                <p>Super Mario series</p>
                <p>2014</p>
            </a>
        </html>
        """
        mock_get.return_value = mock_response

        # Run scraper
        scraper = NintendoAmiiboScraper()
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
        assert luigi["_needs_backfill"] is True
        assert luigi["head"] == "00000000"  # Placeholder
