"""Daily users report, sourced from the Firestore `user_interactions` table.

Every authenticated user-action increments a per-user row (see
``firestore_client.record_interaction``): a hashed user id, a running
interaction count, and first/last seen timestamps. This command reads that
table and reports three numbers for a given day:

    new users        rows whose first_seen falls on the report date
    active users     rows whose last_seen falls on the report date
    total unique     rows that existed by the end of the report date

It emails an HTML summary with a one-row-per-user CSV attachment to
DAILY_REPORT_TO_EMAIL and archives the CSV in GCS. Anonymous traffic never
reaches the table (no hash without a login), so no filtering is needed here.

Designed to be invoked by Cloud Scheduler (via /internal/run-daily-report)
once per day. Safe to run manually for ad-hoc reports via `--date YYYY-MM-DD`.
"""

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError

from tracker import firestore_client


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Email a daily users report from the interactions table, archive CSV in GCS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help=("Report date in YYYY-MM-DD (UTC). " "Defaults to yesterday."),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build the report but don't email or upload to GCS.",
        )
        parser.add_argument(
            "--send-empty",
            action="store_true",
            help=(
                "Send the email + archive even when the table has no users yet. "
                "Default is to skip silently so empty days don't spam the inbox."
            ),
        )

    def handle(self, *args, **options):
        report_date = self._resolve_date(options["date"])
        self.stdout.write(f"Reading user_interactions for {report_date.isoformat()}")

        rows = firestore_client.list_user_interactions()
        stats = self._summarise(rows, report_date)
        self.stdout.write(
            f"{stats['total']} total user(s), "
            f"{len(stats['new_users'])} new, "
            f"{stats['active']} active on {report_date.isoformat()}"
        )

        csv_bytes = self._render_csv(stats["known"], report_date)
        html_body = self._render_html(report_date, stats)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: not emailing or uploading."))
            self.stdout.write(html_body[:1000])
            return

        if not stats["total"] and not options["send_empty"]:
            self.stdout.write(
                self.style.WARNING(
                    "No users in the table yet; skipping email + GCS upload. "
                    "Pass --send-empty to force."
                )
            )
            return

        self._send_email(report_date, html_body, csv_bytes)
        self._upload_to_gcs(report_date, csv_bytes)
        self.stdout.write(self.style.SUCCESS("Daily report sent + archived."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_date(self, raw):
        if raw:
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError(f"Invalid --date: {exc}") from exc
        return (datetime.now(timezone.utc) - timedelta(days=1)).date()

    def _summarise(self, rows, report_date):
        """Split the table into the counts the report needs.

        ``known`` is scoped to users who existed by the end of the report date
        so that a backfilled ``--date`` reports the totals as they stood then,
        rather than as they stand today.
        """
        cutoff = datetime.combine(
            report_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )

        known, new_users, active = [], [], 0
        for row in rows:
            first_seen = self._as_utc(row.get("first_seen"))
            last_seen = self._as_utc(row.get("last_seen"))
            if first_seen is None or first_seen >= cutoff:
                continue
            known.append(row)
            if first_seen.date() == report_date:
                new_users.append(row)
            if last_seen is not None and last_seen.date() == report_date:
                active += 1

        return {
            "known": known,
            "new_users": new_users,
            "active": active,
            "total": len(known),
        }

    def _as_utc(self, value):
        """Normalise a Firestore timestamp to an aware UTC datetime."""
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _render_csv(self, known, report_date):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "user_hash",
                "total_interactions",
                "first_seen",
                "last_seen",
                "is_new",
            ]
        )
        for row in known:
            first_seen = self._as_utc(row.get("first_seen"))
            last_seen = self._as_utc(row.get("last_seen"))
            writer.writerow(
                [
                    row.get("user_hash", ""),
                    row.get("interactions", 0),
                    first_seen.isoformat() if first_seen else "",
                    last_seen.isoformat() if last_seen else "",
                    (
                        "true"
                        if first_seen and first_seen.date() == report_date
                        else "false"
                    ),
                ]
            )
        return buf.getvalue().encode("utf-8")

    def _render_html(self, report_date, stats):
        new_hashes = {r.get("user_hash") for r in stats["new_users"]}

        rows = []
        for row in sorted(stats["known"], key=lambda r: -(r.get("interactions") or 0)):
            user_hash = row.get("user_hash", "")
            first_seen = self._as_utc(row.get("first_seen"))
            last_seen = self._as_utc(row.get("last_seen"))
            badge = (
                ' <span style="color:#0a7">new</span>'
                if user_hash in new_hashes
                else ""
            )
            rows.append(
                f"<tr>"
                f"<td><code>{user_hash}</code>{badge}</td>"
                f"<td>{row.get('interactions', 0)}</td>"
                f"<td>{first_seen.strftime('%Y-%m-%d') if first_seen else ''}</td>"
                f"<td>{last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else ''}</td>"
                f"</tr>"
            )

        table_rows = "\n".join(rows) or '<tr><td colspan="4">No users yet</td></tr>'
        return f"""<html>
<body style="font-family: -apple-system, Segoe UI, sans-serif; color: #222;">
<h2>goozamiibo users report &mdash; {report_date.isoformat()}</h2>
<p>
  <strong>{len(stats['new_users'])}</strong> new user(s) on this day,
  <strong>{stats['total']}</strong> total unique user(s) so far,
  <strong>{stats['active']}</strong> active on this day.
</p>
<p style="color:#666">Counts come from the persistent user_interactions table
(authenticated users only; anonymous traffic is never recorded). Times are UTC.
One row per user attached as CSV. Long-term archive in GCS.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <thead style="background:#f4f4f4">
    <tr>
      <th>user_hash</th><th>total interactions</th>
      <th>first seen</th><th>last seen</th>
    </tr>
  </thead>
  <tbody>
    {table_rows}
  </tbody>
</table>
</body>
</html>"""

    def _send_email(self, report_date, html_body, csv_bytes):
        to_email = getattr(settings, "DAILY_REPORT_TO_EMAIL", "") or ""
        if not to_email:
            raise CommandError("DAILY_REPORT_TO_EMAIL is not set.")
        subject = f"[goozamiibo] Users report — {report_date.isoformat()}"
        message = EmailMessage(
            subject=subject,
            body=html_body,
            to=[to_email],
        )
        message.content_subtype = "html"
        message.attach(
            f"goozamiibo-users-{report_date.isoformat()}.csv",
            csv_bytes,
            "text/csv",
        )
        message.send(fail_silently=False)

    def _upload_to_gcs(self, report_date, csv_bytes):
        bucket_name = getattr(settings, "GCS_REPORTS_BUCKET", "") or ""
        if not bucket_name:
            self.stdout.write(
                self.style.WARNING("GCS_REPORTS_BUCKET unset; skipping archive upload.")
            )
            return
        try:
            from google.cloud import storage
        except ImportError:
            logger.warning("gcs-archive-skipped | google-cloud-storage not installed")
            return
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(f"{report_date.isoformat()}.csv")
        blob.upload_from_string(csv_bytes, content_type="text/csv")
        self.stdout.write(
            self.style.SUCCESS(
                f"Archived to gs://{bucket_name}/{report_date.isoformat()}.csv"
            )
        )
