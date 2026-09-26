#!/bin/sh
set -e

# Only the web container runs migrations and seeding; workers just start.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
  if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    if [ "${CELERY_TASK_ALWAYS_EAGER:-0}" = "1" ]; then
      # No worker (e.g. Render's free plan): every wake-up from sleep is a fresh
      # start, so seeding and the NBU rate run next to the server instead of
      # before it; both are idempotent and the site answers from the database
      # meanwhile. Prices, photos and imports come from the GitHub Actions
      # "Market data" workflow (inline here they would take hours).
      (python manage.py seed_catalog && python manage.py update_exchange_rate) &
    else
      python manage.py seed_catalog
      python manage.py update_exchange_rate
      # Fresh prices and photos are fetched by the Celery worker in the
      # background, so the site is usable immediately.
      python manage.py refresh_market --async || echo "Broker not ready, beat will refresh later."
      if [ "${IMPORT_CATALOG_PAGES:-0}" -gt 0 ]; then
        python manage.py import_hotline --async --pages "$IMPORT_CATALOG_PAGES" \
          || echo "Broker not ready, run import_hotline manually."
      fi
    fi
  fi
fi

exec "$@"
