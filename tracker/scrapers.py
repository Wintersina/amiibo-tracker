import hashlib
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
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
        self.database_path = Path(__file__).parent / "data" / "amiibo_database.json"

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
                match = self.find_best_match(scraped, existing_amiibos)

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
                        self.log_warning(
                            f"No aria-label found in link: {link.get('href', 'unknown')}"
                        )
                        continue

                    # Extract image from img tag
                    image_url = ""
                    img_tag = link.find("img")
                    if img_tag:
                        # Try src first, then data-src (for lazy loading)
                        image_url = img_tag.get("src", "") or img_tag.get(
                            "data-src", ""
                        )
                        # Make sure URL is absolute
                        if image_url and not image_url.startswith("http"):
                            image_url = f"https://www.nintendo.com{image_url}"

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

                    # Skip sets, bundles, and grouped items
                    if self.is_set_or_bundle(name):
                        self.log_info(f"Skipping set/bundle: {name}")
                        continue

                    amiibos.append(
                        {
                            "name": name,
                            "series": self.clean_series(series),
                            "release_date": release_date,
                            "image": image_url,
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
            # Use December 31st as default when only year is known
            # This prevents misleading users that it released early in the year
            return f"{year_match.group(1)}-12-31"

        return None

    def clean_series(self, series_text):
        """Clean series name by removing ' series' suffix"""
        return re.sub(r"\s+series$", "", series_text, flags=re.IGNORECASE)

    def is_set_or_bundle(self, name):
        """
        Check if an amiibo name represents a set, bundle, or grouped item.

        Args:
            name: Amiibo name to check

        Returns:
            True if it's a set/bundle, False if it's an individual amiibo
        """
        name_lower = name.lower()

        # Keywords that indicate sets, bundles, or grouped items
        set_indicators = [
            "starter set",
            "card set",
            "pack",
            "bundle",
            "collection",
            "power-up band",
            "power up band",
            "cards - series",  # e.g., "Cards - Series 5"
            "card series",
            "amiibo cards series",
            "triple pack",
            "3-pack",
            "3 pack",
            "multi-pack",
            "multipack",
            "double pack",
            "2-pack",
            "2 pack",
        ]

        # Check if any indicator is in the name
        for indicator in set_indicators:
            if indicator in name_lower:
                return True

        # Check for patterns like "Series N" at the end (card series)
        if re.search(r"series\s+\d+$", name_lower):
            return True

        return False

    def load_existing_amiibos(self):
        """Load existing amiibos from JSON file"""
        try:
            with self.database_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return data.get("amiibo", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.log_warning("Could not load database", error=str(e))
            return []

    def find_best_match(self, scraped_amiibo, existing_amiibos):
        """
        Find best matching amiibo using fuzzy name matching and date comparison.

        Args:
            scraped_amiibo: Dict with 'name', 'release_date', etc.
            existing_amiibos: List of existing amiibo dicts

        Returns:
            Best matching amiibo or None
        """
        scraped_name = scraped_amiibo.get("name", "")
        scraped_date = scraped_amiibo.get("release_date")

        scraped_clean = self.normalize_name(scraped_name)
        best_match = None
        best_score = 0

        for amiibo in existing_amiibos:
            existing_clean = self.normalize_name(amiibo.get("name", ""))

            # Calculate name similarity
            name_score = self.calculate_similarity(scraped_clean, existing_clean)

            # Boost score if release dates match
            date_boost = 0
            if scraped_date:
                existing_na_date = amiibo.get("release", {}).get("na")
                if existing_na_date and existing_na_date == scraped_date:
                    # Exact date match gives significant boost
                    date_boost = 0.3
                elif existing_na_date and self.dates_are_close(
                    scraped_date, existing_na_date
                ):
                    # Close dates give smaller boost (within 30 days)
                    date_boost = 0.15

            # Combined score
            final_score = min(1.0, name_score + date_boost)

            if final_score > best_score and final_score >= self.min_similarity:
                best_score = final_score
                best_match = amiibo

        if best_match:
            self.log_info(
                f"✓ Match found: '{scraped_name}' -> '{best_match.get('name')}' "
                f"(score: {best_score:.2f})"
            )
        else:
            self.log_warning(
                f"✗ No match for: '{scraped_name}' "
                f"(best score: {best_score:.2f}, threshold: {self.min_similarity})"
            )

        return best_match

    def normalize_name(self, name):
        """
        Normalize name for comparison.

        Handles variants, parentheses, dashes, and special characters.
        """
        name = name.lower()

        # Remove common variant indicators in parentheses
        name = re.sub(
            r"\s*\(.*?\)\s*", " ", name
        )  # Remove (Side Order), (Alterna), etc.

        # Remove common variant suffixes with dashes
        name = re.sub(r"\s*-\s*side order\s*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s*-\s*alterna\s*$", "", name, flags=re.IGNORECASE)

        # Remove special characters but keep spaces
        name = re.sub(r"[^\w\s]", "", name)

        # Normalize whitespace
        name = re.sub(r"\s+", " ", name).strip()

        return name

    def calculate_similarity(self, name1, name2):
        """
        Calculate fuzzy similarity between two names using multiple methods.

        Uses SequenceMatcher for character-level fuzzy matching plus
        word-based matching for better results.
        """
        if not name1 or not name2:
            return 0

        # Method 1: SequenceMatcher for character-level fuzzy matching
        sequence_score = SequenceMatcher(None, name1, name2).ratio()

        # Method 2: Word-based matching (Jaccard similarity)
        words1 = set(name1.split())
        words2 = set(name2.split())

        if words1 and words2:
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            word_score = len(intersection) / len(union)
        else:
            word_score = 0

        # Method 3: Substring bonus
        substring_bonus = 0
        if name1 in name2 or name2 in name1:
            substring_bonus = 0.1

        # Combine scores (weighted average + bonus)
        # Character-level is more important for fuzzy matching
        final_score = (sequence_score * 0.6) + (word_score * 0.4) + substring_bonus

        return min(1.0, final_score)

    def dates_are_close(self, date1, date2, days_threshold=30):
        """
        Check if two dates are within a threshold of each other.

        Args:
            date1: Date string in YYYY-MM-DD format
            date2: Date string in YYYY-MM-DD format
            days_threshold: Maximum days apart to consider "close"

        Returns:
            True if dates are within threshold, False otherwise
        """
        try:
            d1 = datetime.strptime(date1, "%Y-%m-%d")
            d2 = datetime.strptime(date2, "%Y-%m-%d")
            days_apart = abs((d1 - d2).days)
            return days_apart <= days_threshold
        except (ValueError, TypeError):
            return False

    def update_amiibo(self, existing_amiibo, scraped_data):
        """Update existing amiibo with scraped data (release dates only)"""
        updated = False

        if scraped_data["release_date"]:
            existing_release = existing_amiibo.get("release", {})

            if not existing_release.get("na"):
                if not existing_amiibo.get("release"):
                    existing_amiibo["release"] = {}
                existing_amiibo["release"]["na"] = scraped_data["release_date"]
                updated = True

        # Note: Image updates disabled - we never overwrite existing image data
        # Images are only set when creating new placeholder amiibos

        return updated

    def create_placeholder_amiibo(self, scraped_data):
        """
        Create a placeholder amiibo entry with unique ID.

        Generates unique head/tail from name hash to prevent URL collisions.
        """
        release_date = scraped_data["release_date"]

        # Generate unique ID from name to prevent URL collisions
        # Use first 8 chars of SHA256 hash for head and tail
        name_hash = hashlib.sha256(scraped_data["name"].encode()).hexdigest()
        unique_head = f"ff{name_hash[:6]}"  # ff prefix indicates placeholder
        unique_tail = f"ff{name_hash[6:12]}"

        return {
            "amiiboSeries": scraped_data.get("series", "Unknown"),
            "character": scraped_data["name"],
            "gameSeries": scraped_data.get("series", "Unknown"),
            "head": unique_head,
            "image": scraped_data.get("image", ""),
            "name": scraped_data["name"],
            "release": {"na": release_date} if release_date else {},
            "tail": unique_tail,
            "type": "Figure",
            "is_upcoming": True,
        }

    def save_amiibos(self, amiibos):
        """Save amiibos back to JSON file"""
        data = {"amiibo": amiibos}

        with self.database_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def backfill_from_amiiboapi(self, amiibos):
        """
        Backfill placeholder amiibos with complete data from AmiiboAPI.
        Prioritizes amiibos with is_upcoming flag.
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
            needs_backfill = [a for a in amiibos if a.get("is_upcoming")]
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
        placeholder["gameSeries"] = api_amiibo.get(
            "gameSeries", placeholder["gameSeries"]
        )
        placeholder["amiiboSeries"] = api_amiibo.get(
            "amiiboSeries", placeholder["amiiboSeries"]
        )
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

        # Keep is_upcoming flag - will be evaluated in the view based on release dates
        # No need to delete it here
