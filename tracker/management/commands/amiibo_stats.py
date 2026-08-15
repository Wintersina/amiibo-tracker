"""Catalog-wide questions about what users actually track.

Reads the `amiibos` blob off every `user_interactions` document and answers the
things that are otherwise invisible: which amiibos are most collected, which
nobody has, which are rarest among people who do have one, and how many people
hold a specific amiibo.

    manage.py amiibo_stats                       # overview
    manage.py amiibo_stats --top 20              # longer leaderboards
    manage.py amiibo_stats --amiibo 01000000-00000002
    manage.py amiibo_stats --amiibo Mario        # name also works
    manage.py amiibo_stats --csv stats.csv       # full per-amiibo table
    manage.py amiibo_stats --json               # machine-readable overview
    manage.py amiibo_stats --print-token         # token for the HTTP endpoint

The aggregation itself lives in tracker.amiibo_report so this command and
/api/amiibo-stats/ can never disagree.

Counts cover users who have logged in since collection tracking shipped, since
that login is what seeds a user's blob from their sheet.
"""

import csv
import json

from django.core.management.base import BaseCommand, CommandError

from tracker import amiibo_report


class Command(BaseCommand):
    help = "Report on which amiibos users collect and favorite."

    def add_arguments(self, parser):
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="How many entries to show per leaderboard (default 10).",
        )
        parser.add_argument(
            "--amiibo",
            type=str,
            default=None,
            help="Report holders of a single amiibo, by head-tail id or name.",
        )
        parser.add_argument(
            "--csv",
            type=str,
            default=None,
            help="Write the full per-amiibo table to this path.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit the overview as JSON instead of a text table.",
        )
        parser.add_argument(
            "--print-token",
            action="store_true",
            help=(
                "Print the token /api/amiibo-stats/ expects for the currently "
                "loaded DJANGO_SECRET_KEY, then exit."
            ),
        )

    def handle(self, *args, **options):
        if options["print_token"]:
            token = amiibo_report.api_token()
            if not token:
                raise CommandError(
                    "No token can be derived: DJANGO_SECRET_KEY is unset or still "
                    "the unsafe default. Set it (or AMIIBO_STATS_TOKEN) first."
                )
            self.stdout.write(token)
            return

        if options["amiibo"]:
            self._report_one(options["amiibo"])
            return

        report = amiibo_report.build_report(top=options["top"])

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2))
        elif not report["total_users"]:
            self.stdout.write(
                self.style.WARNING(
                    "No users have a tracked-amiibo blob yet. Blobs are written "
                    "on login, so this fills in as people sign in."
                )
            )
            return
        else:
            self._render(report, options["top"])

        if options["csv"]:
            self._write_csv(options["csv"])

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _report_one(self, needle):
        matches = amiibo_report.lookup(needle)
        if not matches:
            raise CommandError(f"No amiibo matches {needle!r}.")
        for match in matches:
            self.stdout.write(
                f"{match['name']}  [{match['id']}]\n"
                f"  collected by {match['users']} of {match['total_users']} "
                f"users ({match['pct']:.0f}%)\n"
                f"  favorited by {match['favorited_by']}"
            )

    def _render(self, report, top):
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{report['total_users']} user(s) with a tracked collection, "
                f"{report['catalog_size']} amiibos in the catalog\n"
            )
        )
        self._table(f"Most collected (top {top})", report["most_collected"])
        self._table(
            f"Rarest, among amiibos someone owns (top {top})", report["rarest_owned"]
        )
        self._table(f"Most favorited (top {top})", report["most_favorited"])

        nobody = report["owned_by_nobody"]
        self.stdout.write(
            f"\nOwned by nobody: {nobody['count']} of {report['catalog_size']} amiibos"
        )
        for entry in nobody["sample"]:
            self.stdout.write(f"  {entry['name']}  [{entry['id']}]")
        remaining = nobody["count"] - len(nobody["sample"])
        if remaining > 0:
            self.stdout.write(f"  ... and {remaining} more")

    def _table(self, title, entries):
        self.stdout.write(f"\n{title}")
        if not entries:
            self.stdout.write("  (none)")
            return
        for entry in entries:
            self.stdout.write(
                f"  {entry['users']:>4} user(s) {entry['pct']:>5.0f}%  "
                f"{entry['name']}  [{entry['id']}]"
            )

    def _write_csv(self, path):
        rows = amiibo_report.full_table()
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(self.style.SUCCESS(f"\nWrote full table to {path}"))
