import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from tracker.helpers import LoggingMixin


class NintendoAmiiboScraper(LoggingMixin):
    """
    Scraper for Nintendo amiibo lineup page.
    Cloud Run compatible - uses file timestamp for cache checking.
    """

    def __init__(self, min_similarity=0.6, cache_hours=6):
        self.min_similarity = min_similarity
        self.cache_hours = cache_hours
        self.database_path = (
            Path(__file__).parent / "data" / "amiibo_database.json"
        )

    def should_run(self):
        """
        Check if scraper should run based on file modification time.
        Cloud Run compatible - no in-memory cache needed.
        """
        if not self.database_path.exists():
            return True

        try:
            # Check file modification time
            mtime = datetime.fromtimestamp(self.database_path.stat().st_mtime)
            age_hours = (datetime.now() - mtime).total_seconds() / 3600

            return age_hours >= self.cache_hours
        except Exception:
            return True

    def run(self, force=False):
        """Run the scraper and update database"""
        if not force and not self.should_run():
            self.log_info("Scraper already ran recently, skipping")
            return {"status": "skipped", "reason": "cache_valid"}

        try:
            self.log_info("Starting Nintendo amiibo scraper")

            # Scrape Nintendo website
            scraped_amiibos = self.scrape_nintendo_amiibos()
            if not scraped_amiibos:
                self.log_warning("No amiibos scraped")
                return {"status": "error", "message": "No amiibos scraped"}

            # Load existing amiibos
            existing_amiibos = self.load_existing_amiibos()

            # Match and update
            matched_count = 0
            new_count = 0
            updated_amiibos = []

            for scraped in scraped_amiibos:
                match = self.find_best_match(scraped["name"], existing_amiibos)

                if match:
                    matched_count += 1
                    if self.update_amiibo(match, scraped):
                        updated_amiibos.append(match["name"])
                else:
                    new_count += 1
                    new_amiibo = self.create_placeholder_amiibo(scraped)
                    existing_amiibos.append(new_amiibo)

            # Backfill placeholders with AmiiboAPI data
            backfilled_count = 0
            if new_count > 0:
                self.log_info("Backfilling new amiibos from AmiiboAPI...")
                backfilled_count = self.backfill_from_amiiboapi(existing_amiibos)

            # Save changes
            if updated_amiibos or new_count > 0 or backfilled_count > 0:
                self.save_amiibos(existing_amiibos)
                self.log_info(
                    "Scraper completed",
                    matched=matched_count,
                    new=new_count,
                    updated=len(updated_amiibos),
                    backfilled=backfilled_count,
                )

            return {
                "status": "success",
                "matched": matched_count,
                "new": new_count,
                "updated": len(updated_amiibos),
                "backfilled": backfilled_count,
            }

        except Exception as e:
            self.log_error("Scraper failed", error=str(e))
            return {"status": "error", "message": str(e)}

    def scrape_nintendo_amiibos(self):
        """Scrape amiibos from Nintendo's lineup page"""
        url = "https://www.nintendo.com/us/amiibo/line-up/"

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            amiibos = []
            amiibo_links = soup.find_all("a", href=re.compile(r"/us/amiibo/detail/"))

            for link in amiibo_links:
                try:
                    # Name is in aria-label attribute
                    name = link.get("aria-label", "").strip()
                    if not name:
                        self.log_warning(f"No aria-label found in link: {link.get('href', 'unknown')}")
                        continue

                    # Find all p tags - first one with "series" is the series name
                    p_tags = link.find_all("p")
                    series = ""
                    date_text = ""

                    for p in p_tags:
                        text = p.get_text(strip=True)
                        if not text:
                            continue

                        # Check if this looks like a date
                        if self.contains_date(text):
                            date_text = text
                        # Otherwise if it contains "series", it's the series name
                        elif not series and "series" in text.lower():
                            series = text

                    release_date = self.parse_release_date(date_text)

                    amiibos.append(
                        {
                            "name": name,
                            "series": self.clean_series(series),
                            "release_date": release_date,
                        }
                    )

                except Exception as e:
                    self.log_warning("Error parsing amiibo link", error=str(e))
                    continue

            return amiibos

        except requests.RequestException as e:
            self.log_error("Request to Nintendo failed", error=str(e))
            return []

    def contains_date(self, text):
        """Check if text contains a date pattern"""
        date_patterns = [
            r"\d{1,2}/\d{1,2}/\d{2,4}",
            r"Available\s+\d",
            r"20\d{2}",
        ]
        return any(re.search(pattern, text) for pattern in date_patterns)

    def parse_release_date(self, date_text):
        """Parse release date from text"""
        if not date_text:
            return None

        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", date_text)
        if date_match:
            date_str = date_match.group(1)
            try:
                if len(date_str.split("/")[2]) == 2:
                    date_obj = datetime.strptime(date_str, "%m/%d/%y")
                else:
                    date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass

        year_match = re.search(r"(20\d{2})", date_text)
        if year_match:
            return f"{year_match.group(1)}-01-01"

        return None

    def clean_series(self, series_text):
        """Clean series name by removing ' series' suffix"""
        return re.sub(r"\s+series$", "", series_text, flags=re.IGNORECASE)

    def load_existing_amiibos(self):
        """Load existing amiibos from JSON file"""
        try:
            with self.database_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return data.get("amiibo", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.log_warning("Could not load database", error=str(e))
            return []

    def find_best_match(self, scraped_name, existing_amiibos):
        """Find best matching amiibo using substring matching"""
        scraped_clean = self.normalize_name(scraped_name)
        best_match = None
        best_score = 0

        for amiibo in existing_amiibos:
            existing_clean = self.normalize_name(amiibo.get("name", ""))
            score = self.calculate_similarity(scraped_clean, existing_clean)

            if score > best_score and score >= self.min_similarity:
                best_score = score
                best_match = amiibo

        return best_match

    def normalize_name(self, name):
        """Normalize name for comparison"""
        name = name.lower()
        name = re.sub(r"[^\w\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def calculate_similarity(self, name1, name2):
        """Calculate similarity between two names"""
        if name1 in name2 or name2 in name1:
            return 0.9

        words1 = set(name1.split())
        words2 = set(name2.split())

        if not words1 or not words2:
            return 0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def update_amiibo(self, existing_amiibo, scraped_data):
        """Update existing amiibo with scraped data"""
        updated = False

        if scraped_data["release_date"]:
            existing_release = existing_amiibo.get("release", {})

            if not existing_release.get("na"):
                if not existing_amiibo.get("release"):
                    existing_amiibo["release"] = {}
                existing_amiibo["release"]["na"] = scraped_data["release_date"]
                updated = True

        return updated

    def create_placeholder_amiibo(self, scraped_data):
        """Create a placeholder amiibo entry"""
        release_date = scraped_data["release_date"]

        return {
            "amiiboSeries": scraped_data.get("series", "Unknown"),
            "character": scraped_data["name"],
            "gameSeries": scraped_data.get("series", "Unknown"),
            "head": "00000000",
            "image": "",
            "name": scraped_data["name"],
            "release": {"na": release_date} if release_date else {},
            "tail": "00000000",
            "type": "Figure",
            "_needs_backfill": True,
        }

    def save_amiibos(self, amiibos):
        """Save amiibos back to JSON file"""
        data = {"amiibo": amiibos}

        with self.database_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def backfill_from_amiiboapi(self, amiibos):
        """
        Backfill placeholder amiibos with complete data from AmiiboAPI.
        Prioritizes amiibos with _needs_backfill flag.
        """
        try:
            # Fetch all amiibos from AmiiboAPI
            self.log_info("Fetching complete amiibo data from AmiiboAPI...")
            response = requests.get("https://amiiboapi.org/api/amiibo/", timeout=30)
            response.raise_for_status()
            api_data = response.json()
            api_amiibos = api_data.get("amiibo", [])

            if not api_amiibos:
                self.log_warning("No amiibos returned from AmiiboAPI")
                return 0

            self.log_info(f"Loaded {len(api_amiibos)} amiibos from AmiiboAPI")

            # Find all amiibos that need backfilling
            needs_backfill = [a for a in amiibos if a.get("_needs_backfill")]
            if not needs_backfill:
                self.log_info("No amiibos need backfilling")
                return 0

            self.log_info(f"Found {len(needs_backfill)} amiibos needing backfill")

            backfilled_count = 0
            for placeholder in needs_backfill:
                # Try to find a match in AmiiboAPI
                match = self.find_amiiboapi_match(placeholder, api_amiibos)

                if match:
                    # Backfill with complete data from AmiiboAPI
                    self.backfill_amiibo_data(placeholder, match)
                    backfilled_count += 1
                    self.log_info(
                        f"Backfilled: {placeholder['name']}",
                        head=match.get("head"),
                        tail=match.get("tail"),
                    )
                else:
                    self.log_warning(
                        f"Could not find AmiiboAPI match for: {placeholder['name']}"
                    )

            return backfilled_count

        except requests.RequestException as e:
            self.log_error("Failed to fetch from AmiiboAPI", error=str(e))
            return 0
        except Exception as e:
            self.log_error("Backfill process failed", error=str(e))
            return 0

    def find_amiiboapi_match(self, placeholder, api_amiibos):
        """Find the best match for a placeholder in AmiiboAPI data"""
        placeholder_name = self.normalize_name(placeholder["name"])
        best_match = None
        best_score = 0

        for api_amiibo in api_amiibos:
            api_name = self.normalize_name(api_amiibo.get("name", ""))
            score = self.calculate_similarity(placeholder_name, api_name)

            # Higher threshold for API matching to ensure accuracy
            if score > best_score and score >= 0.7:
                best_score = score
                best_match = api_amiibo

        return best_match

    def backfill_amiibo_data(self, placeholder, api_amiibo):
        """Update placeholder with complete data from AmiiboAPI"""
        # Update with real IDs
        placeholder["head"] = api_amiibo.get("head", "00000000")
        placeholder["tail"] = api_amiibo.get("tail", "00000000")

        # Update with real data
        placeholder["character"] = api_amiibo.get("character", placeholder["character"])
        placeholder["gameSeries"] = api_amiibo.get("gameSeries", placeholder["gameSeries"])
        placeholder["amiiboSeries"] = api_amiibo.get("amiiboSeries", placeholder["amiiboSeries"])
        placeholder["image"] = api_amiibo.get("image", "")
        placeholder["type"] = api_amiibo.get("type", placeholder.get("type", "Figure"))

        # Merge release dates (keep Nintendo's NA date if we have it)
        api_release = api_amiibo.get("release", {})
        if api_release:
            if "release" not in placeholder:
                placeholder["release"] = {}
            # Keep existing NA date from Nintendo if present
            for region in ["jp", "eu", "au"]:
                if region in api_release and region not in placeholder["release"]:
                    placeholder["release"][region] = api_release[region]
            # Only use API's NA date if we don't have one from Nintendo
            if "na" in api_release and not placeholder["release"].get("na"):
                placeholder["release"]["na"] = api_release["na"]

        # Remove backfill flag
        if "_needs_backfill" in placeholder:
            del placeholder["_needs_backfill"]
