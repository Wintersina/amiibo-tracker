from pathlib import Path
from django.core.management.base import BaseCommand
from tracker.scrapers import NintendoAmiiboScraper


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

        # Use the NintendoAmiiboScraper class
        scraper = NintendoAmiiboScraper(min_similarity=min_similarity)
        scraped_amiibos = scraper.scrape_nintendo_amiibos()

        if not scraped_amiibos:
            self.stdout.write(self.style.ERROR("Failed to scrape amiibos"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Scraped {len(scraped_amiibos)} amiibos from Nintendo")
        )

        # Load existing amiibos
        database_path = scraper.database_path
        existing_amiibos = scraper.load_existing_amiibos()

        self.stdout.write(f"Loaded {len(existing_amiibos)} existing amiibos")

        # Match and update
        matched_count = 0
        new_count = 0
        updates = []

        for scraped in scraped_amiibos:
            match = scraper.find_best_match(scraped, existing_amiibos)

            if match:
                matched_count += 1
                updated = scraper.update_amiibo(match, scraped)
                if updated:
                    updates.append(
                        f"  - Updated: {match['name']} with release date {scraped['release_date']}"
                    )
            else:
                new_count += 1
                new_amiibo = scraper.create_placeholder_amiibo(scraped)
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
            scraper.save_amiibos(existing_amiibos)
            self.stdout.write(
                self.style.SUCCESS(f"\nSaved changes to {database_path}")
            )
        else:
            self.stdout.write(
                self.style.WARNING("\nDry run - no changes saved")
            )
