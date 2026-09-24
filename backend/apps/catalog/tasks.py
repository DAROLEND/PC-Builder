import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .integrations import IntegrationError, fetch_nbu_rate, fetch_price_feed
from .models import Component, ExchangeRate, PriceHistory

logger = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(IntegrationError,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 5},
)
def update_exchange_rate(currency: str = "USD") -> str:
    rate = fetch_nbu_rate(currency)
    ExchangeRate.objects.update_or_create(
        currency=rate.currency, rate_date=rate.rate_date, defaults={"rate": rate.rate}
    )
    logger.info("Exchange rate %s = %s UAH (%s)", rate.currency, rate.rate, rate.rate_date)
    return f"{rate.currency}={rate.rate}"


@shared_task(autoretry_for=(IntegrationError,), retry_backoff=300, retry_kwargs={"max_retries": 3})
def sync_component_prices() -> dict[str, int]:
    """Apply supplier prices and record every change in PriceHistory.

    Only rows whose price actually changed are written, and all writes happen
    in one transaction so a half-applied feed is never visible.
    """
    feed = fetch_price_feed()
    changed: list[Component] = []
    history: list[PriceHistory] = []

    now = timezone.now()
    for component in Component.objects.filter(sku__in=feed.keys()).only("id", "sku", "price"):
        new_price = feed[component.sku]
        if new_price != component.price:
            component.price = new_price
            # bulk_update() bypasses save(), so auto_now is not applied.
            component.updated_at = now
            changed.append(component)
            history.append(PriceHistory(component=component, price=new_price, source="feed"))

    with transaction.atomic():
        Component.objects.bulk_update(changed, ["price", "updated_at"])
        PriceHistory.objects.bulk_create(history)

    unknown = len(feed) - Component.objects.filter(sku__in=feed.keys()).count()
    stats = {"seen": len(feed), "updated": len(changed), "unknown_sku": unknown}
    logger.info("Price sync: %s", stats)
    return stats


@shared_task(soft_time_limit=3 * 60 * 60)
def import_catalog(kinds: list[str], pages: int = 1) -> dict[str, int]:
    """Import new products from the aggregator's category pages (slow, polite)."""
    from .importer import import_category
    from .market_stats import update_market_stats

    created = {}
    for kind in kinds:
        created[kind] = import_category(kind, pages=pages).created
    update_market_stats()
    logger.info("Catalog import: %s", created)
    return created


@shared_task(soft_time_limit=30 * 60)
def refresh_market_listings(limit: int | None = None) -> dict[str, int]:
    """Refresh prices, stock and photos of listings not checked recently.

    Runs in the worker because it is slow on purpose: requests to one host are
    spaced by MARKET_MIN_INTERVAL seconds to stay polite.
    """
    from .market_service import refresh_due_listings

    stats = refresh_due_listings(limit=limit)
    logger.info("Market refresh: %s", stats)
    if stats:
        from apps.alerts.tasks import check_price_watches
        from config.celery import enqueue_best_effort

        enqueue_best_effort(check_price_watches)
    return stats
