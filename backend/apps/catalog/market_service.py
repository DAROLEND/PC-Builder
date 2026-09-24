"""Apply fetched market data to listings and components."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .market import (
    FETCH_DISABLED,
    Fetcher,
    MarketError,
    ProductData,
    fetching_enabled,
    titles_match,
)
from .models import Component, ExchangeRate, MarketListing, PriceHistory

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


def to_usd(amount: Decimal, currency: str, uah_rate: Decimal | None) -> Decimal | None:
    currency = (currency or "").upper()
    if currency == "USD":
        return amount.quantize(CENT)
    if currency in ("UAH", "") and uah_rate:
        return (amount / uah_rate).quantize(CENT, rounding=ROUND_HALF_UP)
    return None  # unknown currency: never guess


def apply_product_data(listing: MarketListing, data: ProductData) -> None:
    listing.title = data.title[:300]
    listing.images = data.images[:10] or listing.images  # keep old photos if none now
    listing.rating = data.rating
    listing.review_count = data.review_count
    listing.last_error = ""
    listing.checked_at = timezone.now()

    if not titles_match(str(listing.component), data.title):
        # Don't touch prices: the URL may now point at a different product.
        listing.status = MarketListing.Status.MISMATCH
        listing.last_error = f"Source title “{data.title[:200]}” does not match."
        return

    if not data.has_price:
        listing.status = MarketListing.Status.NO_OFFERS
        listing.in_stock = False
        listing.offer_count = 0
        return

    listing.status = MarketListing.Status.OK
    listing.low_price = data.low_price
    listing.high_price = max(data.high_price or data.low_price, data.low_price)
    listing.median_price = data.median_price
    listing.currency = (data.currency or "UAH").upper()
    listing.offer_count = data.offer_count
    listing.in_stock = data.in_stock


def update_component_price(component: Component, uah_rate: Decimal | None) -> bool:
    """Set the component price to the typical price of the best verified listing.

    "Typical" is the median of the shop offers when the source lists them, the
    lowest offer otherwise. In-stock listings win; when nothing is in stock, the
    last known market price is still a better estimate than whatever the catalog
    started with. Every call records today's price point (see PriceHistory).
    Returns True when the component price changed.
    """
    best: tuple[bool, Decimal, MarketListing] | None = None
    for listing in component.listings.all():
        if listing.status != MarketListing.Status.OK:
            continue
        typical = listing.median_price or listing.low_price
        usd = to_usd(typical, listing.currency, uah_rate) if typical is not None else None
        if usd is None:
            continue
        candidate = (listing.in_stock is False, usd, listing)  # in-stock sorts first
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return False
    _, price, listing = best
    changed = price != component.price
    low = to_usd(listing.low_price, listing.currency, uah_rate)
    high = to_usd(listing.high_price, listing.currency, uah_rate) if listing.high_price else None
    with transaction.atomic():
        if changed:
            Component.objects.filter(pk=component.pk).update(price=price, updated_at=timezone.now())
        record_daily_price(component, price, low, high, source=listing.source[:32])
    component.price = price
    return changed


def update_shop_count(component: Component) -> int | None:
    """How many shops sell the part now, from its best verified listing."""
    counts = [
        (listing.offer_count or 0) if listing.status == MarketListing.Status.OK else 0
        for listing in MarketListing.objects.filter(component=component)
        if listing.status in (MarketListing.Status.OK, MarketListing.Status.NO_OFFERS)
    ]
    shops = max(counts) if counts else None
    if shops != component.shop_count:
        Component.objects.filter(pk=component.pk).update(shop_count=shops)
        component.shop_count = shops
    return shops


def record_daily_price(
    component: Component,
    price: Decimal,
    low: Decimal | None = None,
    high: Decimal | None = None,
    *,
    source: str,
) -> PriceHistory:
    """One history point per component, source and day; later checks update it."""
    now = timezone.now()
    today = PriceHistory.objects.filter(
        component=component, source=source, recorded_at__date=timezone.localdate(now)
    ).first()
    if today is None:
        return PriceHistory.objects.create(
            component=component, price=price, low_price=low, high_price=high, source=source
        )
    today.price, today.low_price, today.high_price, today.recorded_at = price, low, high, now
    today.save(update_fields=["price", "low_price", "high_price", "recorded_at"])
    return today


def fill_missing_specs(component: Component, data: ProductData) -> bool:
    """Add specs the source knows and we don't. Never overwrites a value.

    Curated parts keep their hand-checked data; catalog-only parts become
    buildable as soon as the source publishes what was missing.
    """
    from .importer import derive_specs

    found = derive_specs(component.category.kind, data.title, data.raw_specs)
    additions = {key: value for key, value in found.items() if key not in component.specs}
    if not additions:
        return False
    component.specs = {**component.specs, **additions}
    component.save(update_fields=["specs", "updated_at"])
    return True


def refresh_listing(listing: MarketListing, fetcher: Fetcher, uah_rate: Decimal | None) -> str:
    if not fetching_enabled():
        return listing.status  # leave the stored data exactly as it is
    data: ProductData | None = None
    try:
        data = fetcher.fetch_product(listing.url)
        apply_product_data(listing, data)
    except MarketError as exc:
        listing.checked_at = timezone.now()
        if exc.code == "no_product_data":
            listing.status = MarketListing.Status.NO_OFFERS
            listing.in_stock = False
            listing.last_error = "The page has no offers right now."
        else:
            listing.status = MarketListing.Status.ERROR
            listing.last_error = str(exc)[:500]
    listing.save()
    update_component_price(listing.component, uah_rate)
    update_shop_count(listing.component)
    if listing.status == MarketListing.Status.OK and data is not None:
        fill_missing_specs(listing.component, data)
        # The source's own daily chart, when it has one (see price_history.py).
        from .price_history import sync_listing_history

        sync_listing_history(listing, fetcher)
    if listing.images and listing.status != MarketListing.Status.MISMATCH:
        # Local import: images.py imports this module's neighbours.
        from .images import mirror_images

        mirror_images(listing.component, listing.images, fetcher)
    return listing.status


def listings_due(stale_hours: int | None = None):
    hours = settings.MARKET_STALE_HOURS if stale_hours is None else stale_hours
    cutoff = timezone.now() - timedelta(hours=hours)
    return (
        MarketListing.objects.filter(component__is_active=True)
        .filter(Q(checked_at__isnull=True) | Q(checked_at__lt=cutoff))
        .select_related("component__manufacturer", "component__category")
        .order_by("checked_at", "id")  # never-checked (NULL) first
    )


def refresh_due_listings(limit: int | None = None, stale_hours: int | None = None) -> dict:
    if not fetching_enabled():
        logger.info(FETCH_DISABLED)
        return {}
    fetcher = Fetcher()
    rate = ExchangeRate.latest_uah_rate()
    stats: dict[str, int] = {}
    for listing in listings_due(stale_hours)[:limit]:
        status = refresh_listing(listing, fetcher, rate)
        stats[status] = stats.get(status, 0) + 1
        logger.info("Listing %s → %s", listing.url, status)
    if stats:
        from .market_stats import update_market_stats

        update_market_stats()
    return stats
