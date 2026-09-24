"""Popularity rank, price-drop and 12-month-low signals, and sorting by them."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.catalog.market_stats import price_signals, update_market_stats
from apps.catalog.models import Component, MarketListing, PriceHistory
from apps.catalog.price_history import parse_popularity

NOW = timezone.now()


def series(days_and_prices):
    return [(NOW - timedelta(days=d), Decimal(p)) for d, p in days_and_prices]


def daily(start_days_ago: int, end_days_ago: int, price):
    return [(d, price) for d in range(start_days_ago, end_days_ago - 1, -1)]


def test_change_compares_weekly_medians():
    # A month ago ~100, now ~90, with one noisy day in each week.
    points = series([*daily(40, 24, "100"), (27, "140"), *daily(23, 0, "90"), (2, "60")])
    change, _ = price_signals(sorted(points), shops=12, now=NOW)
    assert change == Decimal("-10.0")


def test_thin_markets_and_implausible_moves_give_no_signal():
    points = series(daily(40, 24, "440") + daily(23, 0, "100"))  # -77 %: a lone shop left
    assert price_signals(points, shops=30, now=NOW) == (None, False)
    points = series(daily(40, 24, "100") + daily(23, 0, "90"))
    assert price_signals(points, shops=2, now=NOW) == (None, False)  # two shops: noise


def test_year_low_needs_enough_history():
    long = series(daily(200, 31, "100") + daily(30, 0, "80"))
    assert price_signals(long, shops=10, now=NOW)[1] is True
    short = series(daily(60, 0, "80"))
    assert price_signals(short, shops=10, now=NOW)[1] is False


def test_popularity_is_a_weekly_average_ignoring_gaps():
    days = [f"{d:02d}.09.2026" for d in range(1, 11)]
    values = [0, 0, 0, 100, 200, 300, 400, 500, 600, 700]
    payload = {"data": {"chart": {"popularity": [list(p) for p in zip(days, values, strict=True)]}}}
    assert parse_popularity(payload) == 400  # mean of the last 7 non-zero days
    assert parse_popularity({"data": {"chart": {"popularity": []}}}) is None


def test_ranks_are_per_category_and_sorting_puts_unknown_last(api, comp):
    gpus = list(Component.objects.filter(category__kind="gpu").order_by("id")[:3])
    cpu = comp("Ryzen 5 7600")
    for part, popularity in zip([*gpus[:2], cpu], [500, 900, 50], strict=True):
        Component.objects.filter(pk=part.pk).update(popularity=popularity)
    update_market_stats()

    ranks = dict(
        Component.objects.filter(popularity__isnull=False).values_list("id", "popularity_rank")
    )
    assert ranks == {gpus[1].id: 1, gpus[0].id: 2, cpu.id: 1}  # each category has its own #1
    assert Component.objects.get(pk=gpus[2].pk).popularity_rank is None

    body = api.get("/api/components/?category=gpu&ordering=-popularity&page_size=100").json()
    ids = [row["id"] for row in body["results"]]
    assert ids[:2] == [gpus[1].id, gpus[0].id]  # parts without data come after
    assert body["results"][0]["popularity_rank"] == 1


def test_price_drop_sorting_and_fields(api, comp):
    cpu = comp("Ryzen 5 7600")
    MarketListing.objects.create(
        component=cpu, url="https://x.example/cpu", offer_count=20, status="ok"
    )
    PriceHistory.objects.bulk_create(
        PriceHistory(component=cpu, price=Decimal(price), source="hotline.ua", recorded_at=at)
        for at, price in series(daily(45, 24, "200") + daily(23, 0, "180"))
    )
    update_market_stats()

    body = api.get("/api/components/?category=cpu&ordering=price_change_30d").json()
    first = body["results"][0]
    assert first["id"] == cpu.id
    assert first["price_change_30d"] == "-10.0"


# --- Parts sold by too few shops ---------------------------------------------------------


def test_parts_with_few_shops_are_hidden_from_browsing_but_reachable(api, comp):
    lonely, normal = comp("Ryzen 5 7600"), comp("Ryzen 5 9600X")
    MarketListing.objects.create(
        component=lonely, url="https://x.example/1", offer_count=1, status="ok"
    )
    MarketListing.objects.create(
        component=normal, url="https://x.example/2", offer_count=7, status="ok"
    )
    update_market_stats()

    names = {
        r["name"] for r in api.get("/api/components/?category=cpu&page_size=100").json()["results"]
    }
    assert "Ryzen 5 7600" not in names and "Ryzen 5 9600X" in names
    assert "Ryzen 5 5600" in names  # no market data at all: kept

    detail = api.get(f"/api/components/{lonely.slug}/").json()  # builds link to it
    assert (detail["shop_count"], detail["listed"]) == (1, False)
    assert not Component.objects.buildable().filter(pk=lonely.pk).exists()  # advisor skips it


def test_hidden_part_comes_back_when_shops_return(comp):
    from apps.catalog.market_service import update_shop_count

    cpu = comp("Ryzen 5 7600")
    listing = MarketListing.objects.create(
        component=cpu, url="https://x.example/1", offer_count=2, status="ok"
    )
    assert update_shop_count(cpu) == 2
    assert not Component.objects.listed().filter(pk=cpu.pk).exists()
    listing.offer_count = 9
    listing.save()
    assert update_shop_count(cpu) == 9
    assert Component.objects.listed().filter(pk=cpu.pk).exists()
    listing.status = "no_offers"
    listing.save()
    assert update_shop_count(cpu) == 0
