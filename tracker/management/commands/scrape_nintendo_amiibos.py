import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scrape amiibo lineup from Nintendo website and update database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without making changes to the database",
        )
        parser.add_argument(
            "--min-similarity",
            type=float,
            default=0.6,
            help="Minimum similarity score for name matching (0.0-1.0)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        min_similarity = options["min_similarity"]

        self.stdout.write("Fetching Nintendo amiibo lineup...")
        scraped_amiibos = self.scrape_nintendo_amiibos()

        if not scraped_amiibos:
            self.stdout.write(self.style.ERROR("Failed to scrape amiibos"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Scraped {len(scraped_amiibos)} amiibos from Nintendo")
        )

        # Load existing amiibos
        database_path = Path(__file__).parent.parent.parent / "data" / "amiibo_database.json"
        existing_amiibos = self.load_existing_amiibos(database_path)

        self.stdout.write(f"Loaded {len(existing_amiibos)} existing amiibos")

        # Match and update
        matched_count = 0
        new_count = 0
        updates = []

        for scraped in scraped_amiibos:
            match = self.find_best_match(
                scraped["name"], existing_amiibos, min_similarity
            )

            if match:
                matched_count += 1
                updated = self.update_amiibo(match, scraped)
                if updated:
                    updates.append(
                        f"  - Updated: {match['name']} with release date {scraped['release_date']}"
                    )
            else:
                new_count += 1
                new_amiibo = self.create_placeholder_amiibo(scraped)
                existing_amiibos.append(new_amiibo)
                updates.append(f"  + New placeholder: {scraped['name']}")

        # Display results
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"Matched: {matched_count}"))
        self.stdout.write(self.style.WARNING(f"New placeholders: {new_count}"))
        self.stdout.write("=" * 60 + "\n")

        if updates:
            self.stdout.write("Changes:")
            for update in updates[:20]:  # Show first 20 changes
                self.stdout.write(update)
            if len(updates) > 20:
                self.stdout.write(f"  ... and {len(updates) - 20} more")

        # Save changes
        if not dry_run:
            self.save_amiibos(database_path, existing_amiibos)
            self.stdout.write(
                self.style.SUCCESS(f"\nSaved changes to {database_path}")
            )
        else:
            self.stdout.write(
                self.style.WARNING("\nDry run - no changes saved")
            )

    def scrape_nintendo_amiibos(self):
        """Scrape amiibos from Nintendo's lineup page"""
        url = "https://www.nintendo.com/us/amiibo/line-up/"

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            amiibos = []

            # Find all amiibo links
            amiibo_links = soup.find_all("a", href=re.compile(r"/us/amiibo/detail/"))

            for link in amiibo_links:
                try:
                    # Extract name from heading
                    heading = link.find(["h2", "h3", "h4"])
                    if not heading:
                        continue

                    name = heading.get_text(strip=True)

                    # Extract series from paragraph
                    series_elem = link.find("p")
                    series = series_elem.get_text(strip=True) if series_elem else ""

                    # Extract release date - look for date patterns
                    date_text = ""
                    for p in link.find_all("p"):
                        text = p.get_text(strip=True)
                        if self.contains_date(text):
                            date_text = text
                            break

                    release_date = self.parse_release_date(date_text)

                    amiibos.append(
                        {
                            "name": name,
                            "series": self.clean_series(series),
                            "release_date": release_date,
                            "raw_date_text": date_text,
                        }
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f"Error parsing amiibo: {e}")
                    )
                    continue

            return amiibos

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Request failed: {e}"))
            return []

    def contains_date(self, text):
        """Check if text contains a date pattern"""
        # Look for patterns like "04/02/26", "Available 04/02/26", "2026", etc.
        date_patterns = [
            r"\d{1,2}/\d{1,2}/\d{2,4}",  # MM/DD/YY or MM/DD/YYYY
            r"Available\s+\d",
            r"20\d{2}",  # Year like 2026
        ]
        return any(re.search(pattern, text) for pattern in date_patterns)

    def parse_release_date(self, date_text):
        """Parse release date from text"""
        if not date_text:
            return None

        # Try to extract MM/DD/YY or MM/DD/YYYY format
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", date_text)
        if date_match:
            date_str = date_match.group(1)
            try:
                # Try parsing as MM/DD/YY
                if len(date_str.split("/")[2]) == 2:
                    date_obj = datetime.strptime(date_str, "%m/%d/%y")
                else:
                    date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Try to extract just year
        year_match = re.search(r"(20\d{2})", date_text)
        if year_match:
            return f"{year_match.group(1)}-01-01"

        return None

    def clean_series(self, series_text):
        """Clean series name by removing ' series' suffix"""
        return re.sub(r"\s+series$", "", series_text, flags=re.IGNORECASE)

    def load_existing_amiibos(self, database_path):
        """Load existing amiibos from JSON file"""
        try:
            with database_path.open(encoding="utf-8") as f:
                data = json.load(f)
                return data.get("amiibo", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.stdout.write(self.style.WARNING(f"Could not load database: {e}"))
            return []

    def find_best_match(self, scraped_name, existing_amiibos, min_similarity):
        """Find best matching amiibo using substring matching"""
        scraped_clean = self.normalize_name(scraped_name)
        best_match = None
        best_score = 0

        for amiibo in existing_amiibos:
            existing_clean = self.normalize_name(amiibo.get("name", ""))
            score = self.calculate_similarity(scraped_clean, existing_clean)

            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = amiibo

        return best_match

    def normalize_name(self, name):
        """Normalize name for comparison"""
        # Convert to lowercase and remove special characters
        name = name.lower()
        name = re.sub(r"[^\w\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def calculate_similarity(self, name1, name2):
        """Calculate similarity between two names using substring matching"""
        # If one is substring of another
        if name1 in name2 or name2 in name1:
            return 0.9

        # Count matching words
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

        # Update release date if not present or if Nintendo has more specific date
        if scraped_data["release_date"]:
            existing_release = existing_amiibo.get("release", {})

            # If no NA release date, add it
            if not existing_release.get("na"):
                if not existing_amiibo.get("release"):
                    existing_amiibo["release"] = {}
                existing_amiibo["release"]["na"] = scraped_data["release_date"]
                updated = True

        return updated

    def create_placeholder_amiibo(self, scraped_data):
        """Create a placeholder amiibo entry for manual backfill"""
        release_date = scraped_data["release_date"]

        return {
            "amiiboSeries": scraped_data.get("series", "Unknown"),
            "character": scraped_data["name"],
            "gameSeries": scraped_data.get("series", "Unknown"),
            "head": "00000000",  # Placeholder - to be filled manually
            "image": "",  # To be filled manually
            "name": scraped_data["name"],
            "release": {"na": release_date} if release_date else {},
            "tail": "00000000",  # Placeholder - to be filled manually
            "type": "Figure",  # Default type
            "_needs_backfill": True,  # Flag for manual review
        }

    def save_amiibos(self, database_path, amiibos):
        """Save amiibos back to JSON file"""
        data = {"amiibo": amiibos}

        with database_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
