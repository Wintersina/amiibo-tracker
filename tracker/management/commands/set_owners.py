"""Manage who can read /api/amiibo-stats/ from a logged-in browser session.

The allowlist lives in Firestore (app_config/owners) rather than in source: this
repo is public, so committing the addresses would publish them in git history
permanently. Storing it here also means the list can change without a redeploy.

    manage.py set_owners --list
    manage.py set_owners codingsina@gmail.com wintersina@gmail.com

Being merely logged in never grants access — only these addresses do. The
shared token remains a separate, independent way in for automation.
"""

from django.core.management.base import BaseCommand, CommandError

from tracker import amiibo_report, firestore_client


class Command(BaseCommand):
    help = "Set or show the operator allowlist for the amiibo stats API."

    def add_arguments(self, parser):
        parser.add_argument(
            "emails",
            nargs="*",
            help="Addresses to allow. Replaces the existing list.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_only",
            help="Show the current allowlist without changing it.",
        )

    def handle(self, *args, **options):
        if options["list_only"] or not options["emails"]:
            current = firestore_client.get_owner_emails()
            if not current:
                self.stdout.write(
                    self.style.WARNING(
                        "No owners configured. Access falls back to "
                        "DAILY_REPORT_TO_EMAIL, or the shared token."
                    )
                )
                return
            self.stdout.write(f"{len(current)} owner(s):")
            for email in sorted(current):
                self.stdout.write(f"  {email}")
            return

        for email in options["emails"]:
            if "@" not in email:
                raise CommandError(f"{email!r} does not look like an email address.")

        stored = firestore_client.set_owner_emails(options["emails"])
        # The endpoint caches the list for a few minutes; drop it so a change
        # (especially removing someone) takes effect immediately in this process.
        amiibo_report.clear_owner_cache()

        self.stdout.write(self.style.SUCCESS(f"Set {len(stored)} owner(s):"))
        for email in sorted(stored):
            self.stdout.write(f"  {email}")
