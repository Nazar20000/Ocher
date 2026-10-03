#!/bin/sh
set -eu

SQLITE_PATH="${SQLITE_PATH:-/app/db.sqlite3}"
mkdir -p "$(dirname "$SQLITE_PATH")"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --threads 4 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
