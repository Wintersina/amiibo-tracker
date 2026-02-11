#!/bin/sh
set -euo pipefail

if [ "${DJANGO_DB_ENGINE:-django.db.backends.dummy}" != "django.db.backends.dummy" ]; then
    echo "Running database migrations..."
    python manage.py migrate --noinput
else
    echo "Skipping migrations (dummy database backend)"
fi

echo "Starting gunicorn on port 8080..."
exec gunicorn amiibo_tracker.wsgi:application \
    --bind 0.0.0.0:8080 \
    --timeout 120 \
    --workers 2 \
    --worker-class gthread \
    --threads 2