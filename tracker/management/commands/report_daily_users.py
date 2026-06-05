"""Daily active users + actions report.

Queries Grafana Cloud Loki for the prior calendar day's user-action and
page-view events, keeps only events from authenticated users, groups by hashed
user, emails an HTML table summary with a CSV attachment to
DAILY_REPORT_TO_EMAIL, and archives the raw CSV in GCS. Anonymous traffic
(crawlers, logged-out visitors) is ignored, and the report is only sent when at
least one authenticated user had activity.

Designed to be invoked by Cloud Scheduler (via /internal/run-daily-report)
once per day. Safe to run manually for ad-hoc reports via `--date YYYY-MM-DD`.
"""

import csv
import io
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


logger = logging.getLogger(__name__)

# Pull the JSON blob LoggingMixin.log()/log_user_action() append to each line.
CONTEXT_RE = re.compile(r"context=(\{.*\})\s*$")


class Command(BaseCommand):
    help = "Email a daily active users + actions report and archive CSV in GCS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help=("Report date in YYYY-MM-DD (UTC). " "Defaults to yesterday."),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5000,
            help="Max log lines to pull from Loki (default 5000).",
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
                "Send the email + archive even when zero events were found. "
                "Default is to skip silently so empty days don't spam the inbox."
            ),
        )

    def handle(self, *args, **options):
        loki_url = (getattr(settings, "LOKI_QUERY_URL", "") or "").rstrip("/")
        loki_user = getattr(settings, "LOKI_QUERY_USER", "") or ""
        loki_key = getattr(settings, "LOKI_QUERY_API_KEY", "") or ""
        if not (loki_url and loki_user and loki_key):
            raise CommandError(
                "LOKI_QUERY_URL/LOKI_QUERY_USER/LOKI_QUERY_API_KEY are not "
                "configured; cannot pull events."
            )

        report_date = self._resolve_date(options["date"])
        start_dt = datetime.combine(
            report_date, datetime.min.time(), tzinfo=timezone.utc
        )
        end_dt = start_dt + timedelta(days=1)

        self.stdout.write(
            f"Pulling Loki events for {report_date.isoformat()} "
            f"({start_dt.isoformat()} -> {end_dt.isoformat()})"
        )

        events = self._fetch_events(
            loki_url=loki_url,
            loki_user=loki_user,
            loki_key=loki_key,
            start=start_dt,
            end=end_dt,
            limit=options["limit"],
        )
        self.stdout.write(f"Got {len(events)} event(s) from Loki")

        per_user = self._group_by_user(events)
        csv_bytes = self._render_csv(events)
        html_body = self._render_html(report_date, per_user, len(events))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: not emailing or uploading."))
            self.stdout.write(html_body[:1000])
            return

        if not events and not options["send_empty"]:
            self.stdout.write(
                self.style.WARNING(
                    "No events found; skipping email + GCS upload. "
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

    def _fetch_events(self, loki_url, loki_user, loki_key, start, end, limit):
        # LogQL selector: the LokiHandler tags every line with app + env. We
        # pull anything tagged production and then filter to user-action / page-view
        # in Python by parsing the embedded context JSON. Keeping the LogQL
        # broad-then-narrow avoids missing events whose `kind` label was never
        # promoted to a stream label by python-logging-loki.
        query = '{app="amiibo-tracker", env="production"} |~ "kind\\":|event\\":"'
        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "end": str(int(end.timestamp() * 1_000_000_000)),
            "limit": str(limit),
            "direction": "forward",
        }
        url = f"{loki_url}/loki/api/v1/query_range"
        resp = requests.get(url, params=params, auth=(loki_user, loki_key), timeout=30)
        if resp.status_code != 200:
            raise CommandError(
                f"Loki query_range failed: {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json().get("data", {}) or {}

        events = []
        for stream in payload.get("result", []) or []:
            for ts_ns, line in stream.get("values", []) or []:
                ctx = self._extract_context(line)
                if not ctx:
                    continue
                if ctx.get("kind") != "user-action" and ctx.get("event") != "page-view":
                    continue
                # Only report on authenticated users. Anonymous traffic
                # (crawlers, logged-out visitors) is intentionally dropped.
                if not bool(ctx.get("authenticated")):
                    continue
                ts_seconds = int(ts_ns) / 1_000_000_000
                events.append(
                    {
                        "timestamp": datetime.fromtimestamp(
                            ts_seconds, tz=timezone.utc
                        ),
                        "user_hash": ctx.get("user_hash") or "anonymous",
                        "authenticated": bool(ctx.get("authenticated")),
                        "kind": ctx.get("kind") or ctx.get("event") or "unknown",
                        "action": ctx.get("action") or ctx.get("event") or "",
                        "path": ctx.get("path") or "",
                        "method": ctx.get("method") or "",
                    }
                )
        events.sort(key=lambda e: e["timestamp"])
        return events

    def _extract_context(self, line):
        if not line:
            return None
        match = CONTEXT_RE.search(line)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _group_by_user(self, events):
        per_user = defaultdict(
            lambda: {
                "events": 0,
                "actions": defaultdict(int),
                "first_seen": None,
                "last_seen": None,
                "authenticated": False,
                "paths": set(),
            }
        )
        for ev in events:
            bucket = per_user[ev["user_hash"]]
            bucket["events"] += 1
            bucket["actions"][ev["action"] or "(none)"] += 1
            bucket["authenticated"] = bucket["authenticated"] or ev["authenticated"]
            ts = ev["timestamp"]
            if bucket["first_seen"] is None or ts < bucket["first_seen"]:
                bucket["first_seen"] = ts
            if bucket["last_seen"] is None or ts > bucket["last_seen"]:
                bucket["last_seen"] = ts
            if ev["path"]:
                bucket["paths"].add(ev["path"])
        return per_user

    def _render_csv(self, events):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "timestamp_utc",
                "user_hash",
                "authenticated",
                "kind",
                "action",
                "method",
                "path",
            ]
        )
        for ev in events:
            writer.writerow(
                [
                    ev["timestamp"].isoformat(),
                    ev["user_hash"],
                    "true" if ev["authenticated"] else "false",
                    ev["kind"],
                    ev["action"],
                    ev["method"],
                    ev["path"],
                ]
            )
        return buf.getvalue().encode("utf-8")

    def _render_html(self, report_date, per_user, total_events):
        # Every event in the report is from an authenticated user, so per_user
        # only ever contains authenticated buckets.
        authed = list(per_user)

        rows = []
        sorted_users = sorted(
            per_user.items(),
            key=lambda kv: -kv[1]["events"],
        )
        for user_hash, bucket in sorted_users:
            top_actions = sorted(bucket["actions"].items(), key=lambda kv: -kv[1])[:5]
            top_actions_str = ", ".join(
                f"{name} ({count})" for name, count in top_actions
            )
            rows.append(
                f"<tr>"
                f"<td><code>{user_hash}</code></td>"
                f"<td>{bucket['events']}</td>"
                f"<td>{top_actions_str}</td>"
                f"<td>{bucket['first_seen'].strftime('%H:%M:%S') if bucket['first_seen'] else ''}</td>"
                f"<td>{bucket['last_seen'].strftime('%H:%M:%S') if bucket['last_seen'] else ''}</td>"
                f"</tr>"
            )

        table_rows = "\n".join(rows) or '<tr><td colspan="5">No events</td></tr>'
        return f"""<html>
<body style="font-family: -apple-system, Segoe UI, sans-serif; color: #222;">
<h2>goozamiibo DAU report &mdash; {report_date.isoformat()}</h2>
<p>
  <strong>{len(authed)}</strong> authenticated user(s),
  <strong>{total_events}</strong> total event(s).
</p>
<p style="color:#666">Authenticated users only; anonymous traffic is excluded.
Times are UTC. Full event log attached as CSV. Long-term archive in GCS.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <thead style="background:#f4f4f4">
    <tr>
      <th>user_hash</th><th>events</th>
      <th>top actions</th><th>first</th><th>last</th>
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
        subject = f"[goozamiibo] DAU report — {report_date.isoformat()}"
        message = EmailMessage(
            subject=subject,
            body=html_body,
            to=[to_email],
        )
        message.content_subtype = "html"
        message.attach(
            f"goozamiibo-dau-{report_date.isoformat()}.csv",
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
