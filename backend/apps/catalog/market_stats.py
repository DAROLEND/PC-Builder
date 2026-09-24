"""Catalog-wide market statistics: popularity rank, 30-day price change, 12-month low.

Recomputed in one batch after the market refresh (well under a second for the
whole catalog) and stored on ``Component``, so sorting and filtering by them is
a plain indexed query instead of per-request work over ~250k history rows.

The source's daily average is noisy for thinly traded parts: with one or two
shops it jumps with every listing that appears or disappears (a Ryzen 5 3600
"fell 75 %" when a single overpriced shop was joined by normal ones). So the
price signals compare *weekly medians*, are computed only for parts sold by
enough shops right now, and ignore moves too large to be a real price change.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from django.db.models import Count, F, Max, Q, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from .models import Component, MarketListing, PriceHistory

WINDOW_DAYS = 7
MIN_SHOPS = 5
MAX_PLAUSIBLE_CHANGE = Decimal(40)  # %, larger moves are market-structure artifacts
YEAR_LOW_MIN_DAYS = 90
YEAR_LOW_TOLERANCE = Decimal("1.01")  # averages wobble by a few hryvnias day to day


def _window(points: list[tuple], end, days: int = WINDOW_DAYS) -> Decimal | None:
    values = [price for at, price in points if end - timedelta(days=days) < at <= end]
    return Decimal(median(values)) if values else None


def price_signals(points: list[tuple], shops: int | None, now) -> tuple[Decimal | None, bool]:
    """(change over 30 days in %, at the 12-month low) for one part's history."""
    if not points or (shops or 0) < MIN_SHOPS:
        return None, False
    current = _window(points, now)
    month_ago = _window(points, now - timedelta(days=30))
    change = None
    if current and month_ago:
        change = ((current - month_ago) / month_ago * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
        if abs(change) > MAX_PLAUSIBLE_CHANGE:
            change = None
    year = [price for at, price in points if at >= now - timedelta(days=365)]
    long_enough = points[0][0] <= now - timedelta(days=YEAR_LOW_MIN_DAYS)
    at_low = bool(long_enough and current and year and current <= min(year) * YEAR_LOW_TOLERANCE)
    return change, at_low


def update_market_stats() -> int:
    """Recompute the stats for every component. Returns how many rows changed."""
    now = timezone.now()
    history: dict[int, list[tuple]] = defaultdict(list)
    for component_id, at, price in (
        PriceHistory.objects.filter(recorded_at__gte=now - timedelta(days=400))
        .order_by("component_id", "recorded_at")
        .values_list("component_id", "recorded_at", "price")
    ):
        history[component_id].append((at, price))

    ranks = dict(
        Component.objects.filter(is_active=True, popularity__isnull=False)
        .annotate(
            rank=Window(
                RowNumber(),
                partition_by=[F("category_id")],
                order_by=[F("popularity").desc(), F("id").asc()],
            )
        )
        .values_list("id", "rank")
    )
    ok = Q(listings__status=MarketListing.Status.OK)
    components = Component.objects.annotate(
        # Same rule as market_service.update_shop_count(): verified listings only.
        shops=Max("listings__offer_count", filter=ok),
        checked=Count(
            "listings",
            filter=Q(
                listings__status__in=[MarketListing.Status.OK, MarketListing.Status.NO_OFFERS]
            ),
        ),
    ).only("id", "popularity_rank", "price_change_30d", "at_year_low", "shop_count")
    changed = []
    for row in components:
        change, at_low = price_signals(history.get(row.id, []), row.shops, now)
        rank = ranks.get(row.id)
        shops = row.shops if row.shops is not None else (0 if row.checked else None)
        new = (rank, change, at_low, shops)
        if (row.popularity_rank, row.price_change_30d, row.at_year_low, row.shop_count) != new:
            row.popularity_rank, row.price_change_30d, row.at_year_low, row.shop_count = new
            changed.append(row)
    Component.objects.bulk_update(
        changed,
        ["popularity_rank", "price_change_30d", "at_year_low", "shop_count"],
        batch_size=500,
    )
    return len(changed)
