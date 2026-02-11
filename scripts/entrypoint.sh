#!/bin/sh
set -euo pipefail

python manage.py migrate --noinput

exec gunicorn amiibo_tracker.wsgi:application \
    --bind 0.0.0.0:8080 \
    --timeout 120 \
    --workers 2 \
    --worker-class gthread \
    --threads 2
