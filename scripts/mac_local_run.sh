#!/usr/bin/env bash
set -euo pipefail

# Locate the project root (directory containing manage.py)
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_ROOT"

export OAUTHLIB_INSECURE_TRANSPORT=1

python manage.py migrate
python manage.py runserver
