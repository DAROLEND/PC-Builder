"""Price history from hotline.ua's own chart.

The product page draws its price chart from ``/svc/frontend-api/graphql``
(query ``chart(productPath)``): daily average, minimum and maximum over the
last year, twice a month before that, in UAH and USD. It is an internal,
undocumented endpoint, used here with the project owner's consent and under
the same rules as every other request (robots.txt, throttling, honest
User-Agent). If it changes or fails, nothing breaks: we keep recording our own
daily points (see ``market_service.record_daily_price``).

Both sources write ``PriceHistory`` rows with ``source="hotline.ua"``, one per
day. Chart points replace our own for the same day, and our own points after
the chart's last day are dropped once the chart covers the listing, so the
line never jumps between two methods (hotline averages the offers, we take
their median for the headline price).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from .market import Fetcher, MarketError, fetching_enabled
from .models import Component, MarketListing, PriceHistory

logger = logging.getLogger(__name__)

CHART_URL = "https://hotline.ua/svc/frontend-api/graphql"
CHART_QUERY = (
    "query getChart($path:String!){chart(productPath:$path)"
    "{priceUAH minPriceUAH maxPriceUAH priceUSD popularity}}"
)
SOURCE = "hotline.ua"
CENT = Decimal("0.01")


@dataclass(frozen=True)
class ChartPoint:
    day: date
    price: Decimal  # USD, the source's average
    low: Decimal | None  # USD
    high: Decimal | None  # USD


def product_path(url: str) -> str | None:
    """'https://hotline.ua/ua/computer-processory/amd-ryzen-5-5500/' -> 'amd-ryzen-5-5500'."""
    parts = urlsplit(url)
    if not parts.netloc.endswith("hotline.ua"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    return segments[-1] if len(segments) >= 2 else None


def _series(raw) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    for item in raw or []:
        try:
            stamp, value = item
            day = datetime.strptime(stamp, "%d.%m.%Y").date()
            amount = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError):
            continue
        if amount > 0:  # the source uses 0 for "no data"
            out[day] = amount
    return out


def parse_chart(payload: dict) -> list[ChartPoint]:
    chart = ((payload or {}).get("data") or {}).get("chart") or {}
    uah, usd = _series(chart.get("priceUAH")), _series(chart.get("priceUSD"))
    low_uah, high_uah = _series(chart.get("minPriceUAH")), _series(chart.get("maxPriceUAH"))
    points = []
    for day in sorted(usd):
        price = usd[day].quantize(CENT, ROUND_HALF_UP)
        # The source converts at its own daily rate; reuse it for the range.
        rate = uah[day] / usd[day] if day in uah else None

        def to_usd(series: dict[date, Decimal], rate=rate, day=day) -> Decimal | None:
            if rate is None or day not in series:
                return None
            return (series[day] / rate).quantize(CENT, ROUND_HALF_UP)

        points.append(ChartPoint(day, price, to_usd(low_uah), to_usd(high_uah)))
    return points


POPULARITY_DAYS = 7


def parse_popularity(payload: dict) -> int | None:
    """The source's interest index, averaged over its last week (it is noisy day to day)."""
    chart = ((payload or {}).get("data") or {}).get("chart") or {}
    series = _series(chart.get("popularity"))
    if not series:
        return None
    recent = [series[day] for day in sorted(series)[-POPULARITY_DAYS:]]
    return round(sum(recent) / len(recent))


def fetch_chart(fetcher: Fetcher, listing_url: str) -> tuple[list[ChartPoint], int | None]:
    path = product_path(listing_url)
    if not path:
        return [], None
    payload = fetcher.post_json(
        CHART_URL,
        {"operationName": "getChart", "variables": {"path": path}, "query": CHART_QUERY},
    )
    if payload.get("errors"):
        raise MarketError("chart_error", str(payload["errors"])[:200])
    return parse_chart(payload), parse_popularity(payload)


def _stamp(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(12, 0)))


@transaction.atomic
def store_chart(component: Component, points: list[ChartPoint]) -> int:
    """Upsert one row per chart day. Returns how many rows were added or changed."""
    if not points:
        return 0
    existing = {
        timezone.localdate(row.recorded_at): row
        for row in PriceHistory.objects.filter(component=component, source=SOURCE)
    }
    new, changed = [], []
    for point in points:
        row = existing.get(point.day)
        if row is None:
            new.append(
                PriceHistory(
                    component=component,
                    price=point.price,
                    low_price=point.low,
                    high_price=point.high,
                    source=SOURCE,
                    recorded_at=_stamp(point.day),
                )
            )
        elif (row.price, row.low_price, row.high_price) != (point.price, point.low, point.high):
            row.price, row.low_price, row.high_price = point.price, point.low, point.high
            row.recorded_at = _stamp(point.day)
            changed.append(row)
    PriceHistory.objects.bulk_create(new)
    PriceHistory.objects.bulk_update(changed, ["price", "low_price", "high_price", "recorded_at"])
    # Our own median-based points after the chart's last day would make the
    # line jump between two methods; the chart catches up within a day or two.
    last = points[-1].day
    stale = [row.pk for day, row in existing.items() if day > last]
    PriceHistory.objects.filter(pk__in=stale).delete()
    return len(new) + len(changed)


def sync_listing_history(listing: MarketListing, fetcher: Fetcher) -> int | None:
    """Pull the source's chart for a listing. None when the source has none."""
    if not fetching_enabled() or not product_path(listing.url):
        return None
    try:
        points, popularity = fetch_chart(fetcher, listing.url)
    except MarketError as exc:
        logger.info("No price chart for %s: %s", listing.url, exc)
        return None
    if popularity is not None:
        Component.objects.filter(pk=listing.component_id).update(popularity=popularity)
    if not points:
        return None
    return store_chart(listing.component, points)
