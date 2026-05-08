#!/bin/sh

set -e

echo "Running database migrations..."
python ticketing_project/manage.py migrate --noinput

echo "Seeding initial data..."
python ticketing_project/manage.py seed_event

echo "Starting Gunicorn..."
exec gunicorn ticketing_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --threads 2 \
    --worker-class gthread \
    --chdir /app/ticketing_project
