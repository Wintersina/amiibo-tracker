#!/bin/bash
# Idempotent bootstrap for Grafana Cloud Loki secrets in GCP Secret Manager.
#
# Creates (or adds a new version to) two secrets:
#   - loki-api-key   : the Grafana Cloud API token for log shipping
#   - loki-hash-salt : random salt used to hash user emails before shipping
#
# Safe to run multiple times. Re-running with --rotate-salt generates a fresh
# salt (invalidates historical hash continuity — only do this on purpose).
#
# Usage:
#   PROJECT_ID=my-gcp-project ./scripts/setup-loki-secrets.sh
#   PROJECT_ID=my-gcp-project LOKI_API_KEY=glc_xxx ./scripts/setup-loki-secrets.sh
#   PROJECT_ID=my-gcp-project ./scripts/setup-loki-secrets.sh --rotate-salt


set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
API_KEY_SECRET="${API_KEY_SECRET:-loki-api-key}"
HASH_SALT_SECRET="${HASH_SALT_SECRET:-loki-hash-salt}"
ROTATE_SALT=false

for arg in "$@"; do
  case "$arg" in
    --rotate-salt) ROTATE_SALT=true ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [ -z "$PROJECT_ID" ]; then
  echo "Error: PROJECT_ID environment variable is required." >&2
  echo "  export PROJECT_ID=your-gcp-project-id" >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "Error: gcloud CLI not found on PATH." >&2
  exit 1
fi

echo "Project: $PROJECT_ID"

echo "Ensuring Secret Manager API is enabled..."
gcloud services enable secretmanager.googleapis.com --project="$PROJECT_ID" >/dev/null

secret_exists() {
  gcloud secrets describe "$1" --project="$PROJECT_ID" >/dev/null 2>&1
}

write_secret_value() {
  local name="$1"
  local value="$2"

  if secret_exists "$name"; then
    echo "  - $name exists; adding new version"
    printf '%s' "$value" \
      | gcloud secrets versions add "$name" \
          --project="$PROJECT_ID" \
          --data-file=- >/dev/null
  else
    echo "  - $name missing; creating"
    printf '%s' "$value" \
      | gcloud secrets create "$name" \
          --project="$PROJECT_ID" \
          --replication-policy=automatic \
          --data-file=- >/dev/null
  fi
}

# --- Loki API key --------------------------------------------------------
LOKI_API_KEY_VALUE="${LOKI_API_KEY:-}"

if [ -z "$LOKI_API_KEY_VALUE" ] && ! secret_exists "$API_KEY_SECRET"; then
  echo
  echo "Paste your Grafana Cloud API token (input hidden):"
  read -rs LOKI_API_KEY_VALUE
  echo
fi

if [ -n "$LOKI_API_KEY_VALUE" ]; then
  echo "Writing $API_KEY_SECRET..."
  write_secret_value "$API_KEY_SECRET" "$LOKI_API_KEY_VALUE"
else
  echo "Skipping $API_KEY_SECRET (already exists; pass LOKI_API_KEY=... to rotate)"
fi

# --- Hash salt -----------------------------------------------------------
if secret_exists "$HASH_SALT_SECRET" && [ "$ROTATE_SALT" = false ]; then
  echo "Skipping $HASH_SALT_SECRET (already exists; pass --rotate-salt to regenerate)"
else
  SALT_VALUE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "Writing $HASH_SALT_SECRET..."
  write_secret_value "$HASH_SALT_SECRET" "$SALT_VALUE"
fi

echo
echo "Done. Add these to your GitHub Actions secrets:"
echo "  LOKI_URL               = https://logs-prod-042.grafana.net"
echo "  LOKI_USER              = 1554017"
echo "  LOKI_API_KEY_SECRET    = $API_KEY_SECRET"
echo "  LOKI_HASH_SALT_SECRET  = $HASH_SALT_SECRET"
