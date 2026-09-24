"""Price history from the source's chart (hotline.ua GraphQL)."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
import responses
from django.utils import timezone

from apps.catalog.market import Fetcher
from apps.catalog.models import MarketListing, PriceHistory
from apps.catalog.price_history import (
    CHART_URL,
    parse_chart,
    product_path,
    store_chart,
    sync_listing_history,
)

LISTING_URL = "https://hotline.ua/ua/computer-processory/amd-ryzen-5-7600/"


def chart_payload(days: list[str], uah: list[int], usd: list[float], low=None, high=None):
    def series(values):
        return [[d, v] for d, v in zip(days, values, strict=True)]

    return {
        "data": {
            "chart": {
                "priceUAH": series(uah),
                "priceUSD": series(usd),
                "minPriceUAH": series(low or [0] * len(days)),
                "maxPriceUAH": series(high or [0] * len(days)),
            }
        }
    }


def fetcher() -> Fetcher:
    return Fetcher(user_agent="TestBot", min_interval=0)


def test_product_path_only_for_the_source():
    assert product_path(LISTING_URL) == "amd-ryzen-5-7600"
    assert product_path("https://shop.example/ua/cpu/amd-ryzen-5-7600/") is None


def test_parse_chart_converts_the_range_at_the_sources_own_rate():
    payload = chart_payload(
        ["01.09.2026", "02.09.2026"],
        uah=[8000, 8200],
        usd=[200.0, 205.0],
        low=[7600, 0],  # 0 = no data upstream
        high=[9000, 9020],
    )
    first, second = parse_chart(payload)
    assert (first.day, first.price, first.low, first.high) == (
        date(2026, 9, 1),
        Decimal("200.00"),
        Decimal("190.00"),  # 7600 UAH at that day's 40 UAH/USD
        Decimal("225.00"),
    )
    assert second.low is None and second.high == Decimal("225.50")


def test_parse_chart_tolerates_garbage():
    assert parse_chart({}) == []
    assert parse_chart({"data": {"chart": {"priceUSD": [["bad date", 1], ["01.09.2026"]]}}}) == []


def test_store_chart_is_idempotent_and_replaces_own_points(comp):
    cpu = comp("Ryzen 5 7600")
    today = timezone.localdate()
    # Our own median-based point for today, before the chart covers today.
    PriceHistory.objects.create(component=cpu, price=Decimal("250.00"), source="hotline.ua")
    days = [(today - timedelta(days=n)).strftime("%d.%m.%Y") for n in (3, 2, 1)]
    points = parse_chart(chart_payload(days, uah=[8000, 8100, 8200], usd=[200, 202.5, 205]))

    assert store_chart(cpu, points) == 3
    assert store_chart(cpu, points) == 0  # nothing changed
    rows = PriceHistory.objects.filter(component=cpu).order_by("recorded_at")
    assert [r.price for r in rows] == [Decimal("200.00"), Decimal("202.50"), Decimal("205.00")]

    changed = parse_chart(chart_payload(days, uah=[8000, 8100, 8400], usd=[200, 202.5, 210]))
    assert store_chart(cpu, changed) == 1
    assert PriceHistory.objects.filter(component=cpu).count() == 3


@pytest.fixture
def listing(comp):
    return MarketListing.objects.create(component=comp("Ryzen 5 7600"), url=LISTING_URL)


def test_sync_posts_the_chart_query_under_robots_rules(listing):
    payload = chart_payload(["01.09.2026"], uah=[8000], usd=[200])
    with responses.RequestsMock() as mocked:
        mocked.get("https://hotline.ua/robots.txt", body="User-agent: *\nDisallow: /go/\n")
        mocked.post(CHART_URL, json=payload)
        assert sync_listing_history(listing, fetcher()) == 1
        request = mocked.calls[-1].request
    body = json.loads(request.body)
    assert body["variables"] == {"path": "amd-ryzen-5-7600"}
    assert "chart(productPath:$path)" in body["query"]
    assert request.headers["User-Agent"] == "TestBot"


def test_sync_respects_robots_and_failures(listing):
    with responses.RequestsMock() as mocked:
        mocked.get("https://hotline.ua/robots.txt", body="User-agent: *\nDisallow: /svc/\n")
        assert sync_listing_history(listing, fetcher()) is None
        assert len(mocked.calls) == 1  # the API was never called
    with responses.RequestsMock() as mocked:
        mocked.get("https://hotline.ua/robots.txt", status=404)
        mocked.post(CHART_URL, status=500)
        assert sync_listing_history(listing, fetcher()) is None
    with responses.RequestsMock() as mocked:
        mocked.get("https://hotline.ua/robots.txt", status=404)
        mocked.post(CHART_URL, json={"errors": [{"message": "Unknown field"}]})
        assert sync_listing_history(listing, fetcher()) is None
    assert not PriceHistory.objects.filter(component=listing.component).exists()
