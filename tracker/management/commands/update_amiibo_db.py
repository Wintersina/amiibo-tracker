"""Refresh tracker/data/amiibo_database.json from the live goozamiibo API.

Hits the production API (which proxies the upstream amiibo source), diffs the
result against the local JSON by (head, tail) pair, and only writes when the
content actually changes — so re-running on no-op produces a byte-identical
file and a clean git status.

Usage:
    python manage.py update_amiibo_db                # apply diff, write file
    python manage.py update_amiibo_db --dry-run      # show diff, don't write
    python manage.py update_amiibo_db --api-url URL  # point at a different API
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

DEFAULT_API_URL = "https://goozamiibo.com/api/amiibo/"

LOCAL_DB = (
    Path(__file__).resolve().parents[2] / "data" / "amiibo_database.json"
)

# Fields we treat as canonical. Anything else returned by the API is ignored
# so we don't drift on derived/enrichment fields the live app may add.
CANONICAL_FIELDS = (
    "amiiboSeries",
    "character",
    "gameSeries",
    "head",
    "image",
    "name",
    "release",
    "tail",
    "type",
)

MAX_PREVIEW_LINES = 25


class Command(BaseCommand):
    help = (
        "Sync tracker/data/amiibo_database.json with the live amiibo API. "
        "Only writes when content changed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-url",
            default=DEFAULT_API_URL,
            help=f"API endpoint to fetch from (default: {DEFAULT_API_URL})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the diff and exit without writing the file.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=30.0,
            help="HTTP timeout in seconds (default: 30).",
        )

    def handle(self, *args, **opts):
        api_url = opts["api_url"]
        dry_run = opts["dry_run"]
        timeout = opts["timeout"]

        remote = self._fetch_remote(api_url, timeout)
        self.stdout.write(f"  fetched {len(remote)} amiibo")

        local_payload, local_amiibos = self._load_local()

        diff = self._compute_diff(local_amiibos, remote)
        self._print_summary(diff)

        if not diff["added"] and not diff["removed"] and not diff["changed"]:
            self.stdout.write(self.style.SUCCESS("✓ already up to date — no changes"))
            return

        self._print_details(diff)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n(dry-run) not writing — re-run without --dry-run to apply"
                )
            )
            return

        self._write_local(local_payload, remote)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ wrote {LOCAL_DB.relative_to(Path.cwd()) if LOCAL_DB.is_relative_to(Path.cwd()) else LOCAL_DB} "
                f"({len(remote)} amiibo)"
            )
        )

    # ------------------------------------------------------------------ fetch

    def _fetch_remote(self, api_url: str, timeout: float) -> list[dict]:
        self.stdout.write(f"→ fetching {api_url}")
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "goozamiibo-update-amiibo-db/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise CommandError(f"fetch failed: HTTP {e.code} from {api_url}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise CommandError(f"fetch failed: {e}") from e

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CommandError(f"API response was not valid JSON: {e}") from e

        if not isinstance(payload, dict) or "amiibo" not in payload:
            raise CommandError(
                "API response missing 'amiibo' key (got: "
                + ", ".join(sorted(payload.keys() if isinstance(payload, dict) else []))
                + ")"
            )

        amiibos = payload["amiibo"]
        if not isinstance(amiibos, list):
            raise CommandError("'amiibo' field is not a list")

        return [self._canonicalize(a) for a in amiibos]

    @staticmethod
    def _canonicalize(amiibo: dict) -> dict:
        """Keep only canonical fields, in canonical order. Drops API-only
        enrichment fields (like imgwebp, gamesSwitch usage data) that would
        otherwise create false-positive diffs."""
        return {f: amiibo[f] for f in CANONICAL_FIELDS if f in amiibo}

    # ------------------------------------------------------------------ load

    def _load_local(self) -> tuple[dict, list[dict]]:
        if not LOCAL_DB.exists():
            self.stdout.write(
                self.style.WARNING(f"  local file not found, will create: {LOCAL_DB}")
            )
            return {"amiibo": []}, []

        try:
            payload = json.loads(LOCAL_DB.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"local file is not valid JSON: {e}") from e

        amiibos = payload.get("amiibo", []) if isinstance(payload, dict) else []
        if not isinstance(amiibos, list):
            raise CommandError("local file's 'amiibo' field is not a list")

        return payload, amiibos

    # ------------------------------------------------------------------ diff

    def _compute_diff(self, local: list[dict], remote: list[dict]) -> dict:
        local_index = {self._key(a): a for a in local if self._key(a)}
        remote_index = {self._key(a): a for a in remote if self._key(a)}

        local_keys = set(local_index)
        remote_keys = set(remote_index)

        added = sorted(remote_keys - local_keys)
        removed = sorted(local_keys - remote_keys)

        changed = []
        for key in sorted(local_keys & remote_keys):
            l, r = local_index[key], remote_index[key]
            # Compare on canonical fields only — l may have legacy fields that
            # _canonicalize wouldn't have stripped on disk.
            l_canon = {f: l.get(f) for f in CANONICAL_FIELDS if f in l}
            if l_canon != r:
                field_diffs = {
                    f: (l.get(f), r.get(f))
                    for f in CANONICAL_FIELDS
                    if l.get(f) != r.get(f)
                }
                changed.append((key, r.get("name") or l.get("name") or "?", field_diffs))

        return {
            "added": [(k, remote_index[k].get("name") or "?") for k in added],
            "removed": [(k, local_index[k].get("name") or "?") for k in removed],
            "changed": changed,
        }

    @staticmethod
    def _key(amiibo: dict) -> tuple[str, str] | None:
        head, tail = amiibo.get("head"), amiibo.get("tail")
        if not head or not tail:
            return None
        return head, tail

    # ------------------------------------------------------------------ output

    def _print_summary(self, diff: dict) -> None:
        self.stdout.write("")
        self.stdout.write("— diff summary —")
        self.stdout.write(f"  added:   {len(diff['added'])}")
        self.stdout.write(f"  removed: {len(diff['removed'])}")
        self.stdout.write(f"  changed: {len(diff['changed'])}")

    def _print_details(self, diff: dict) -> None:
        if diff["added"]:
            self.stdout.write("\nNew amiibo:")
            for (head, tail), name in diff["added"][:MAX_PREVIEW_LINES]:
                self.stdout.write(f"  + {name}  [{head}-{tail}]")
            self._print_overflow(len(diff["added"]))

        if diff["removed"]:
            self.stdout.write("\nRemoved from API:")
            for (head, tail), name in diff["removed"][:MAX_PREVIEW_LINES]:
                self.stdout.write(f"  - {name}  [{head}-{tail}]")
            self._print_overflow(len(diff["removed"]))

        if diff["changed"]:
            self.stdout.write("\nChanged fields:")
            for (head, tail), name, fields in diff["changed"][:MAX_PREVIEW_LINES]:
                self.stdout.write(f"  ~ {name}  [{head}-{tail}]")
                for fname, (before, after) in fields.items():
                    self.stdout.write(
                        f"      {fname}: {before!r}  →  {after!r}"
                    )
            self._print_overflow(len(diff["changed"]))

    def _print_overflow(self, total: int) -> None:
        if total > MAX_PREVIEW_LINES:
            self.stdout.write(f"  ... and {total - MAX_PREVIEW_LINES} more")

    # ------------------------------------------------------------------ write

    def _write_local(self, payload: dict, remote: list[dict]) -> None:
        # Preserve any top-level keys other than 'amiibo' that may exist.
        new_payload = dict(payload) if isinstance(payload, dict) else {}
        new_payload["amiibo"] = remote
        # Match the existing file's formatting: 2-space indent, trailing newline.
        LOCAL_DB.write_text(
            json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
