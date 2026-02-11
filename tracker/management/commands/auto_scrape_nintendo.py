from django.core.management.base import BaseCommand
from tracker.scrapers import NintendoAmiiboScraper


class Command(BaseCommand):
    help = "Auto-run Nintendo amiibo scraper (meant for scheduled tasks)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force run even if cache is still valid",
        )
        parser.add_argument(
            "--min-similarity",
            type=float,
            default=0.6,
            help="Minimum similarity score for name matching (0.0-1.0)",
        )

    def handle(self, *args, **options):
        force = options["force"]
        min_similarity = options["min_similarity"]

        scraper = NintendoAmiiboScraper(min_similarity=min_similarity)

        self.stdout.write("Running Nintendo amiibo scraper...")

        result = scraper.run(force=force)

        if result["status"] == "skipped":
            self.stdout.write(
                self.style.WARNING(f"Skipped: {result.get('reason', 'cached')}")
            )
        elif result["status"] == "error":
            self.stdout.write(
                self.style.ERROR(f"Error: {result.get('message', 'Unknown error')}")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Success! Matched: {result['matched']}, New: {result['new']}, Updated: {result['updated']}"
                )
            )
