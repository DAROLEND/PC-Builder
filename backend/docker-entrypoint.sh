#!/bin/sh
set -e

# Only the web container runs migrations and seeding; workers just start.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
  if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    python manage.py seed_catalog
    # Also on every start: a free host without Celery beat still gets today's rate.
    python manage.py update_exchange_rate
    # Without a worker (CELERY_TASK_ALWAYS_EAGER=1, e.g. Render's free plan) these
    # would run inline for hours and the server would never start listening;
    # there the GitHub Actions "Market data" workflow does this job.
    if [ "${CELERY_TASK_ALWAYS_EAGER:-0}" != "1" ]; then
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
