import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.pricing import AmiiboPriceRefreshService


class Command(BaseCommand):
    help = "Refresh AmiiboDex price estimates from eBay and store snapshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of amiibo to refresh in this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Call eBay and print a summary without writing Firestore snapshots.",
        )
        parser.add_argument(
            "--local-cache",
            action="store_true",
            help="Write snapshots to the gitignored local JSON cache instead of Firestore.",
        )

    def handle(self, *args, **options):
        if options["local_cache"]:
            os.environ["AMIIBO_PRICE_USE_LOCAL_CACHE"] = "1"

        amiibos = self._load_amiibos()
        result = AmiiboPriceRefreshService().refresh(
            amiibos,
            limit=options["limit"],
            save=not options["dry_run"],
        )

        status = result.get("status")
        if status == "skipped":
            if result.get("reason") == "firestore_credentials_missing":
                self.stdout.write(
                    self.style.WARNING(
                        "Skipped: firestore_credentials_missing. "
                        "Run with --dry-run to test eBay without Firestore, or run "
                        "`gcloud auth application-default login` before saving locally."
                    )
                )
                return
            if result.get("reason") == "ebay_auth_failed":
                self.stdout.write(
                    self.style.WARNING(
                        "Skipped: ebay_auth_failed. "
                        f"Environment was {result.get('environment', 'unknown')}. "
                        "If you are using sandbox keys, set EBAY_ENV=sandbox in .env "
                        "or run `EBAY_ENV=sandbox make seed-prices-dry LIMIT=1`."
                    )
                )
                return
            if result.get("reason") == "ebay_token_request_failed":
                self.stdout.write(
                    self.style.WARNING(
                        "Skipped: ebay_token_request_failed. "
                        f"Environment was {result.get('environment', 'unknown')}. "
                        f"Error: {result.get('message', 'unknown')}"
                    )
                )
                return
            self.stdout.write(
                self.style.WARNING(f"Skipped: {result.get('reason', 'unknown')}")
            )
            return

        if status == "partial":
            self.stdout.write(
                self.style.WARNING(
                    "Partial refresh: "
                    f"processed={result['processed']} "
                    f"updated={result['updated']} "
                    f"priced={result.get('priced', 0)} "
                    f"unavailable={result.get('unavailable', 0)} "
                    f"already_current={result.get('already_current', 0)} "
                    f"failed={result['failed']}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Dry run complete' if result.get('dry_run') else 'Price refresh complete'}: "
                f"environment={result.get('environment', 'unknown')} "
                f"processed={result['processed']} updated={result['updated']} "
                f"priced={result.get('priced', 0)} "
                f"unavailable={result.get('unavailable', 0)}"
                f" already_current={result.get('already_current', 0)}"
                f"{' local_cache=tracker/data/amiibo_price_cache.local.json' if options['local_cache'] else ''}"
            )
        )

    def _load_amiibos(self):
        data_path = (
            Path(__file__).resolve().parents[2] / "data" / "amiibo_database.json"
        )
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        amiibos = payload.get("amiibo", [])
        return [
            amiibo
            for amiibo in amiibos
            if amiibo.get("amiiboSeries") != "Pragmata"
            and amiibo.get("gameSeries") != "Pragmata"
        ]
