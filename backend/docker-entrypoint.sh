#!/bin/sh
set -e

# Only the web container runs migrations and seeding; workers just start.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
  if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    python manage.py seed_catalog
    # Fresh prices, photos and the USD/UAH rate are fetched by the Celery
    # worker in the background, so the site is usable immediately.
    python manage.py refresh_market --async || echo "Broker not ready, beat will refresh later."
    if [ "${IMPORT_CATALOG_PAGES:-0}" -gt 0 ]; then
      python manage.py import_hotline --async --pages "$IMPORT_CATALOG_PAGES" \
        || echo "Broker not ready, run import_hotline manually."
    fi
  fi
fi

exec "$@"
