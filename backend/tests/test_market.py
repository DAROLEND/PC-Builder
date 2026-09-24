import json
from datetime import date
from decimal import Decimal

import pytest
import responses

from apps.catalog.market import (
    Fetcher,
    MarketError,
    extract_product,
    model_tokens,
    parse_decimal,
    titles_match,
)
from apps.catalog.market_service import refresh_listing, to_usd
from apps.catalog.models import Component, ExchangeRate, MarketListing, PriceHistory

URL = "https://hotline.example/ua/computer-processory/amd-ryzen-7-9800x3d/"
ROBOTS = "https://hotline.example/robots.txt"


def ld_page(product: dict, extra: str = "") -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(product)}</script>{extra}'
        "</head><body>...</body></html>"
    )


AGGREGATE = {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "AMD Ryzen 7 9800X3D (100-100001084WOF)",
    "image": ["https://img.example/1.jpg", "https://img.example/2.jpg"],
    "offers": {
        "@type": "AggregateOffer",
        "lowPrice": 19299,
        "highPrice": "27 930,00",
        "priceCurrency": "UAH",
        "offerCount": 67,
        "availability": "https://schema.org/InStock",
    },
    "aggregateRating": {"ratingValue": 4.8, "reviewCount": 5},
}

# --- parsing (no database) -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (19299, Decimal("19299.00")),
        ("27 930,00", Decimal("27930.00")),
        ("19 299", Decimal("19299.00")),
        ("1,299.50", Decimal("1299.50")),
        ("abc", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == expected


def test_aggregate_offer_from_json_ld():
    data = extract_product(ld_page(AGGREGATE), URL)
    assert data.title.startswith("AMD Ryzen 7 9800X3D")
    assert (data.low_price, data.high_price) == (Decimal("19299.00"), Decimal("27930.00"))
    assert data.currency == "UAH"
    assert data.offer_count == 67
    assert data.in_stock is True
    assert data.rating == Decimal("4.80")
    assert data.images == ["https://img.example/1.jpg", "https://img.example/2.jpg"]


def test_list_of_offers_and_graph_and_broken_block():
    graph = {
        "@graph": [
            {"@type": "BreadcrumbList"},
            {
                "@type": "Product",
                "name": "Corsair RM850x",
                "image": {"@type": "ImageObject", "url": "/img/psu.jpg"},
                "offers": [
                    {"price": "6500", "priceCurrency": "UAH", "availability": "OutOfStock"},
                    {"price": "6278", "priceCurrency": "UAH", "availability": "InStock"},
                ],
            },
        ]
    }
    broken = '<script type="application/ld+json">{not json</script>'
    data = extract_product(ld_page(graph, extra=broken), "https://shop.example/p/1")
    assert data.low_price == Decimal("6278.00")
    assert data.high_price == Decimal("6500.00")
    assert data.offer_count == 2
    assert data.in_stock is True  # at least one offer in stock
    assert data.images == ["https://shop.example/img/psu.jpg"]  # relative URL resolved


def test_microdata_fallback():
    html = """
      <meta property="og:title" content="Процесор AMD Ryzen 7 9800X3D">
      <meta property="og:image" content="https://i.shop.example/9800x3d.jpg">
      <span itemprop="price" content="27930"></span>
      <meta itemprop="priceCurrency" content="UAH">
      <link itemprop="availability" href="https://schema.org/InStock">
    """
    data = extract_product(html, "https://shop.example/p/2")
    assert data.low_price == Decimal("27930.00")
    assert data.currency == "UAH"
    assert data.in_stock is True
    assert data.images == ["https://i.shop.example/9800x3d.jpg"]


def test_page_without_product_data():
    assert extract_product("<html><title>Hotline</title></html>", URL) is None


@pytest.mark.parametrize(
    ("ours", "theirs", "match"),
    [
        ("AMD Ryzen 7 9800X3D", "AMD Ryzen 7 9800X3D (100-100001084WOF)", True),
        ("AMD Ryzen 7 9800X3D", "AMD Ryzen 7 7800X3D (100-100000910WOF)", False),
        ("ASUS TUF Gaming GeForce RTX 5070 Ti 16GB", "ASUS TUF-RTX5070TI-O16G-GAMING", True),
        (
            "Kingston FURY Beast 16GB (2x8GB) DDR4-3200",
            "Kingston FURY 16 GB (2x8GB) DDR4 3200 MHz",
            True,
        ),
        ("Fractal Design North", "Fractal Design North Charcoal Black", True),  # nothing to verify
    ],
)
def test_titles_match(ours, theirs, match):
    assert titles_match(ours, theirs) is match


def test_model_tokens_skip_capacities_and_units():
    assert model_tokens("Vengeance 64GB (2x32GB) DDR5-6000 1300W") == ["ddr5", "6000"]


# --- fetching: robots.txt and HTTP errors --------------------------------------------


@responses.activate
def test_fetcher_respects_robots_txt():
    responses.get(ROBOTS, body="User-agent: *\nDisallow: /ua/computer-processory/\n")
    with pytest.raises(MarketError) as exc:
        Fetcher(user_agent="TestBot", min_interval=0).fetch_product(URL)
    assert exc.value.code == "robots_disallowed"
    assert len(responses.calls) == 1  # the product page was never requested


@responses.activate
def test_fetcher_http_errors():
    responses.get(ROBOTS, status=404)  # no robots.txt → allowed
    responses.get(URL, status=404)
    with pytest.raises(MarketError) as exc:
        Fetcher(user_agent="TestBot", min_interval=0).fetch_product(URL)
    assert exc.value.code == "not_found"


@responses.activate
def test_fetcher_sends_honest_user_agent():
    responses.get(ROBOTS, status=404)
    responses.get(URL, body=ld_page(AGGREGATE))
    Fetcher(user_agent="PCBuilderBot/1.0", min_interval=0).fetch_product(URL)
    assert responses.calls[-1].request.headers["User-Agent"] == "PCBuilderBot/1.0"


# --- applying data to the catalog ------------------------------------------------------


@pytest.fixture
def rate(db):
    return ExchangeRate.objects.create(
        currency="USD", rate=Decimal("40.0000"), rate_date=date(2026, 9, 1)
    ).rate


@pytest.fixture
def cpu(comp):
    return comp("Ryzen 7 9800X3D")


def refresh(listing, rate, html):
    with responses.RequestsMock() as mocked:
        mocked.get(ROBOTS, status=404)
        mocked.get(listing.url, body=html)
        return refresh_listing(listing, Fetcher(user_agent="TestBot", min_interval=0), rate)


def test_ok_listing_updates_price_and_history(cpu, rate):
    listing = MarketListing.objects.create(component=cpu, url=URL)
    assert refresh(listing, rate, ld_page(AGGREGATE)) == MarketListing.Status.OK

    cpu.refresh_from_db()
    assert cpu.price == Decimal("482.48")  # 19299 UAH / 40
    assert PriceHistory.objects.filter(component=cpu, source="hotline.example").count() == 1
    listing.refresh_from_db()
    assert listing.offer_count == 67 and listing.images and listing.checked_at


def test_same_price_is_not_logged_twice(cpu, rate):
    listing = MarketListing.objects.create(component=cpu, url=URL)
    refresh(listing, rate, ld_page(AGGREGATE))
    refresh(listing, rate, ld_page(AGGREGATE))
    assert PriceHistory.objects.filter(component=cpu).count() == 1


def test_mismatched_product_does_not_touch_price(cpu, rate):
    old_price = cpu.price
    listing = MarketListing.objects.create(component=cpu, url=URL)
    other = {**AGGREGATE, "name": "AMD Ryzen 5 7600 (100-100001015BOX)"}
    assert refresh(listing, rate, ld_page(other)) == MarketListing.Status.MISMATCH
    cpu.refresh_from_db()
    assert cpu.price == old_price


def test_out_of_stock_price_is_used_only_when_nothing_is_in_stock(cpu, rate):
    listing = MarketListing.objects.create(component=cpu, url=URL)
    sold_out = {**AGGREGATE, "offers": {**AGGREGATE["offers"], "availability": "OutOfStock"}}
    refresh(listing, rate, ld_page(sold_out))
    cpu.refresh_from_db()
    assert cpu.price == Decimal("482.48")  # last known market price beats the seed price

    MarketListing.objects.create(
        component=cpu,
        url="https://shop.example/in-stock",
        status=MarketListing.Status.OK,
        low_price=Decimal("500.00"),  # dearer, but you can actually buy it
        currency="USD",
        in_stock=True,
    )
    refresh(listing, rate, ld_page(sold_out))
    cpu.refresh_from_db()
    assert cpu.price == Decimal("500.00")


def test_placeholder_images_are_dropped():
    product = {**AGGREGATE, "image": ["https://hotline.ua/public/i/img-265.gif", "/img/real.jpg"]}
    data = extract_product(ld_page(product), URL)
    assert data.images == ["https://hotline.example/img/real.jpg"]


def test_page_without_offers_marks_listing(cpu, rate):
    listing = MarketListing.objects.create(component=cpu, url=URL)
    assert refresh(listing, rate, "<html>no offers</html>") == MarketListing.Status.NO_OFFERS


def test_cheapest_listing_wins_and_usd_is_used_as_is(cpu, rate):
    MarketListing.objects.create(
        component=cpu,
        url="https://shop.example/a",
        status=MarketListing.Status.OK,
        low_price=Decimal("450.00"),
        currency="USD",
        in_stock=True,
    )
    listing = MarketListing.objects.create(component=cpu, url=URL)
    refresh(listing, rate, ld_page(AGGREGATE))  # 482.48 USD equivalent
    cpu.refresh_from_db()
    assert cpu.price == Decimal("450.00")


def test_to_usd_never_guesses_unknown_currency():
    assert to_usd(Decimal("100"), "EUR", Decimal("40")) is None
    assert to_usd(Decimal("100"), "UAH", None) is None


# --- API -----------------------------------------------------------------------------------


def test_component_api_exposes_photo_and_market(api, cpu):
    MarketListing.objects.create(
        component=cpu,
        url=URL,
        status=MarketListing.Status.OK,
        low_price=Decimal("19299.00"),
        high_price=Decimal("27930.00"),
        currency="UAH",
        offer_count=67,
        in_stock=True,
        images=["https://img.example/1.jpg"],
    )
    data = api.get(f"/api/components/{cpu.slug}/").json()
    assert data["image"] == "https://img.example/1.jpg"
    assert data["market"]["low_price"] == "19299.00"
    assert data["market"]["offer_count"] == 67
    assert data["market"]["source"] == "hotline.example"


def test_component_list_query_count_is_constant(db, api, django_assert_max_num_queries):
    for comp in Component.objects.all()[:10]:
        MarketListing.objects.create(
            component=comp, url=f"https://x.example/{comp.pk}", images=["i"]
        )
    with django_assert_max_num_queries(5):  # rate + count + page + listings + photos
        api.get("/api/components/?page_size=50")


def test_staff_can_attach_listing_by_url(api, user, cpu, rate):
    api.force_authenticate(user)
    assert api.post(f"/api/components/{cpu.slug}/listings/", {"url": URL}).status_code == 403

    user.is_staff = True
    user.save()
    with responses.RequestsMock() as mocked:
        mocked.get(ROBOTS, status=404)
        mocked.get(URL, body=ld_page(AGGREGATE))
        resp = api.post(f"/api/components/{cpu.slug}/listings/", {"url": URL})
    assert resp.status_code == 201, resp.data
    assert resp.data["status"] == "ok"
    assert resp.data["title"].startswith("AMD Ryzen 7 9800X3D")
    assert api.post(f"/api/components/{cpu.slug}/listings/", {"url": URL}).status_code == 400
